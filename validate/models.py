import uuid
from django.db import models

class MessageVersion(models.Model):
    version_code = models.CharField(max_length=10, unique=True)
    xml_schema = models.TextField()

    class Meta:
        db_table = 'message_version'

class DocumentFields(models.Model):
    field = models.CharField(max_length=50)
    version = models.ForeignKey(MessageVersion, on_delete=models.CASCADE)
    context = models.CharField(max_length=100)
    xpath = models.CharField(max_length=100)
    tag = models.CharField(max_length=50)
    description = models.TextField()

    class Meta:
        db_table = 'document_fields'

class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message_version = models.ForeignKey(MessageVersion, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    timestamp = models.DateTimeField(null=True, blank=True)  # Разрешаем NULL
    signature = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = 'message'

class Operation(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    transaction_date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3)
    operation_type = models.CharField(max_length=50)

    class Meta:
        db_table = 'operation'

class Members(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    member_name = models.CharField(max_length=255)

    class Meta:
        db_table = 'members'

class Sender(models.Model):
    name = models.CharField(max_length=255)
    inn = models.CharField(max_length=12)

    class Meta:
        db_table = 'sender'

class MessageXML(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    xml_content = models.TextField()
    xml_url_link = models.CharField(max_length=255)

    class Meta:
        db_table = 'message_xml'

class Error(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    error_code = models.CharField(max_length=10)
    error_message = models.TextField()

    class Meta:
        db_table = 'error'

class Rule(models.Model):
    document_field = models.ForeignKey(DocumentFields, on_delete=models.CASCADE)
    version = models.ForeignKey(MessageVersion, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'rule'

class DataFormat(models.Model):
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE)
    predicate = models.CharField(max_length=255, blank=True)
    dataformat = models.CharField(max_length=50)
    length = models.IntegerField(null=True, blank=True)
    error_template = models.CharField(max_length=255)

    class Meta:
        db_table = 'data_format'

class Requirement(models.Model):
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE)
    predicate = models.CharField(max_length=255, blank=True)
    is_required = models.BooleanField(default=False)
    error_template = models.CharField(max_length=255)

    class Meta:
        db_table = 'requirement'