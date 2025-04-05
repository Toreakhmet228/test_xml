from celery import shared_task
from .work_with_xml.v1.worklxml import validate_xml
import os
@shared_task(ignore_result=True)
def process_xml_file(file_path):
    result = validate_xml(file_path)
    if result["status"] == "failed":
        print(f"[DEBUG] Валидация не пройдена: {result['errors']}")
    else:
        print(f"[DEBUG] Валидация успешна: {result['file']}")
    os.remove(file_path)
    print(f"[DEBUG] Файл {file_path} удалён")