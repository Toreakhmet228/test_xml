import os
import time
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'valxml.settings')
django.setup()

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from validate.tasks import process_xml_file

class WatcherHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        file_path = event.src_path
        file_name = os.path.basename(file_path)
        if file_name.endswith('.xml'):
            print(f"New file detected: {file_name}")
            print(f"Full path: {file_path}")
            if os.path.exists(file_path):
                print(f"File exists: {file_path}")
                process_xml_file.delay(file_path)
                print(f"Task sent to Celery for processing: {file_path}")
            else:
                print(f"Error: File does not exist: {file_path}")

def start_watching():
    watch_path = "/app/in"
    if not os.path.exists(watch_path):
        os.makedirs(watch_path)  # Создаём директорию, если её нет
        print(f"Created directory: {watch_path}")
    event_handler = WatcherHandler()
    observer = Observer()
    observer.schedule(event_handler, path=watch_path, recursive=False)
    observer.start()

    print(f"Started watching directory: {watch_path}")
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            print("Watcher stopped")
            break

    observer.join()

if __name__ == "__main__":
    start_watching()