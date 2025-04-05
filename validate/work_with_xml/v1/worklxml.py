import os
import re
import uuid
from datetime import datetime
import pytz
from lxml import etree
from django.conf import settings
from django.core.exceptions import ValidationError
from validate.models import MessageVersion, DocumentFields, Message, Operation, Members, Sender, MessageXML, Error, Rule, Requirement
from storages.backends.s3boto3 import S3Boto3Storage
import boto3
from botocore.exceptions import ClientError

BASE_DIR = settings.BASE_DIR
storage = S3Boto3Storage()

s3_client = boto3.client(
    's3',
    endpoint_url=settings.AWS_S3_ENDPOINT_URL,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
)

def ensure_bucket_exists(bucket_name):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            print(f"Бакет {bucket_name} не существует, создаём...")
            try:
                s3_client.create_bucket(Bucket=bucket_name)
                print(f"Бакет {bucket_name} успешно создан.")
            except ClientError as create_error:
                print(f"Ошибка при создании бакета: {create_error}")
        else:
            print(f"Ошибка при проверке бакета: {e}")

class Validator:
    @staticmethod
    def check_date_format(value):
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$', value)) and len(value) == 19

    @staticmethod
    def check_amount_format(value):
        try:
            decimal_part = str(float(value)).split('.')[-1]
            return len(decimal_part) <= 2
        except (ValueError, IndexError):
            return False

def save_error_to_db(message, errors):
    try:
        for error in errors:
            Error.objects.create(
                message=message,
                error_code=error["error_code"],
                error_message=error["error_message"]
            )
    except Exception as e:
        print(f"Ошибка при сохранении ошибок в БД: {e}")

def create_notification_file(document_id, status, errors=None, timestamp=None, version="1.0"):
    out_dir = os.path.join(BASE_DIR, "out")
    try:
        os.makedirs(out_dir, exist_ok=True)
        file_name = f"{document_id}.{status}Notification.xml"
        file_path = os.path.join(out_dir, file_name)

        root = etree.Element("Notification")
        etree.SubElement(root, "Status").text = "Accepted" if status == "Accepting" else "Rejected"
        etree.SubElement(root, "DocumentID").text = str(document_id)
        etree.SubElement(root, "TimeStamp").text = timestamp if timestamp else datetime.now(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S")
        signed_data = etree.SubElement(root, "SignedData")
        etree.SubElement(signed_data, "Signature").text = "BASE64_ENCODED_SIGNATURE"

        if status == "Accepting":
            processing_details = etree.SubElement(root, "ProcessingDetails")
            etree.SubElement(processing_details, "Version").text = version
            etree.SubElement(processing_details, "ProcessingTime").text = datetime.now(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S")
            etree.SubElement(processing_details, "Message").text = "Document successfully validated and processed."
        else:
            etree.SubElement(root, "Version").text = version
            if errors:
                errors_element = etree.SubElement(root, "Errors")
                for error in errors:
                    error_element = etree.SubElement(errors_element, "Error")
                    etree.SubElement(error_element, "Code").text = error["error_code"]
                    etree.SubElement(error_element, "Message").text = error["error_message"]

        tree = etree.ElementTree(root)
        tree.write(file_path, encoding="utf-8", xml_declaration=True, pretty_print=True)

        minio_path = f"notifications/{file_name}"
        ensure_bucket_exists(settings.AWS_STORAGE_BUCKET_NAME)
        with open(file_path, 'rb') as f:
            storage.save(minio_path, f)
        print(f"Файл {file_name} сохранен в MinIO по пути {minio_path}")
        return file_path
    except Exception as e:
        print(f"Ошибка при создании уведомления: {e}")
        return None

def validate_xml(file_path):
    try:
        # Парсинг XML
        try:
            tree = etree.parse(file_path)
            root = tree.getroot()
        except etree.LxmlError as e:
            return {"status": "failed", "errors": [{"error_code": "E009", "error_message": f"XML parsing error: {str(e)}"}]}

        # Проверка DocumentID
        document_id = root.findtext("DocumentID")
        if not document_id:
            return {"status": "failed", "errors": [{"error_code": "E000", "error_message": "Missing DocumentID"}]}

        try:
            uuid.UUID(document_id)
        except ValueError:
            return {"status": "failed", "errors": [{"error_code": "E007", "error_message": f"Invalid UUID: {document_id}"}]}

        # Проверка обязательных тегов
        errors = []
        timestamp_str = root.findtext("TimeStamp")
        if not timestamp_str:
            errors.append({"error_code": "E003", "error_message": "Missing TimeStamp"})
        elif not Validator.check_date_format(timestamp_str):
            errors.append({"error_code": "E004", "error_message": "Invalid TimeStamp format"})
        else:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.UTC)

        signature = root.findtext("SignedData/Signature") or ""
        if not signature:
            errors.append({"error_code": "E005", "error_message": "Missing Signature in SignedData"})

        if root.tag != "ExportData":
            errors.append({"error_code": "E002", "error_message": "Root tag must be ExportData"})

        # Проверка версии
        version = root.findtext("Version")
        message_version = None
        if not version:
            errors.append({"error_code": "E017", "error_message": "Missing Version tag"})
        else:
            try:
                message_version = MessageVersion.objects.get(version_code=version)
            except MessageVersion.DoesNotExist:
                errors = [{"error_code": "E001", "error_message": f"Unsupported version: {version}"}]

        # Создание или обновление Message
        if errors:
            try:
                message, created = Message.objects.get_or_create(
                    id=document_id,
                    defaults={"message_version": None, "timestamp": None, "signature": signature}
                )
                save_error_to_db(message, errors)
                error_file_path = create_notification_file(document_id, "Denied", errors, timestamp_str, version)
                return {"status": "failed", "errors": errors, "error_file": error_file_path}
            except Exception as e:
                return {"status": "failed", "errors": [{"error_code": "E010", "error_message": f"Failed to save message: {str(e)}"}]}

        try:
            message, created = Message.objects.get_or_create(
                id=document_id,
                defaults={"message_version": message_version, "timestamp": timestamp, "signature": signature}
            )
            if not created:
                message.message_version = message_version
                message.timestamp = timestamp
                message.signature = signature
                message.save()
        except ValidationError as e:
            return {"status": "failed", "errors": [{"error_code": "E011", "error_message": f"Invalid data for Message: {str(e)}"}]}

        # Обработка Operation
        operation_node = root.find(".//Operation")
        if operation_node is not None:
            try:
                Operation.objects.create(
                    message=message,
                    transaction_date=operation_node.findtext("TransactionDate"),
                    amount=operation_node.findtext("Amount"),
                    currency=operation_node.findtext("Currency"),
                    operation_type=operation_node.findtext("OperationType")
                )
            except Exception as e:
                errors.append({"error_code": "E012", "error_message": f"Failed to save Operation: {str(e)}"})

        # Обработка Members (все участники)
        members_nodes = root.findall(".//Member")
        if members_nodes:
            for member_node in members_nodes:
                try:
                    Members.objects.create(
                        message=message,
                        member_name=member_node.findtext("MemberName"),
                        # Предполагается, что в модели Members есть поля member_id и member_role
                        # Если их нет, нужно обновить модель
                    )
                except Exception as e:
                    errors.append({"error_code": "E013", "error_message": f"Failed to save Members: {str(e)}"})

        # Обработка Sender
        sender_node = root.find(".//Sender")
        if sender_node is not None:
            try:
                Sender.objects.create(
                    name=sender_node.findtext("SenderName"),
                    inn=sender_node.findtext("SenderINN")
                    # Предполагается, что в модели Sender есть поле sender_id
                    # Если его нет, нужно обновить модель
                )
            except Exception as e:
                errors.append({"error_code": "E014", "error_message": f"Failed to save Sender: {str(e)}"})

        # Проверка правил валидации
        rules = Rule.objects.filter(version=message_version, is_active=True)
        for rule in rules:
            try:
                requirements = Requirement.objects.filter(rule=rule)
                field_value = root.findtext(rule.document_field.xpath)

                for req in requirements:
                    if req.predicate:
                        predicate_parts = req.predicate.split(" = ")
                        if len(predicate_parts) == 2:
                            predicate_field, predicate_value = predicate_parts
                            actual_value = root.findtext(predicate_field)
                            if actual_value == predicate_value.strip("'"):
                                if req.is_required and not field_value:
                                    errors.append({
                                        "error_code": "E008",
                                        "error_message": req.error_template.format(DocumentField=rule.document_field.field)
                                    })

                if rule.document_field.field == "TimeStamp" and field_value and not Validator.check_date_format(field_value):
                    errors.append({"error_code": "E004", "error_message": "Invalid timestamp format"})
                elif rule.document_field.field == "Amount" and field_value and not Validator.check_amount_format(field_value):
                    errors.append({"error_code": "E005", "error_message": "Invalid amount format"})
            except Exception as e:
                errors.append({"error_code": "E015", "error_message": f"Error in rule validation: {str(e)}"})

        # Проверка Amount и Currency
        amount = root.findtext(".//Operation/Amount")
        currency = root.findtext(".//Operation/Currency")
        if amount and not currency:
            errors.append({"error_code": "E006", "error_message": "Currency is required when Amount is present"})

        # Сохранение XML в MinIO
        try:
            xml_content = etree.tostring(root, encoding="utf-8").decode("utf-8")
            minio_xml_path = f"original/{document_id}.xml"
            ensure_bucket_exists(settings.AWS_STORAGE_BUCKET_NAME)
            with open(file_path, 'rb') as f:
                storage.save(minio_xml_path, f)
            MessageXML.objects.create(
                message=message,
                xml_content=xml_content,
                xml_url_link=storage.url(minio_xml_path)
            )
            print(f"Исходный XML сохранен в MinIO по пути {minio_xml_path}")
        except Exception as e:
            errors.append({"error_code": "E016", "error_message": f"Failed to save XML to MinIO: {str(e)}"})

        if errors:
            save_error_to_db(message, errors)
            error_file_path = create_notification_file(document_id, "Denied", errors, timestamp_str, version)
            return {"status": "failed", "errors": errors, "error_file": error_file_path}

        success_file_path = create_notification_file(document_id, "Accepting", timestamp=timestamp_str, version=version)
        return {"status": "success", "file": success_file_path}

    except Exception as e:
        return {"status": "failed", "errors": [{"error_code": "E999", "error_message": f"Unexpected error: {str(e)}"}]}