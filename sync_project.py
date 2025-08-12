#!/usr/bin/env python3

import concurrent.futures
import fnmatch
import os
from pathlib import Path
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Any
from dotenv import load_dotenv
import json
import datetime


from sync_item import SyncItem
from yandex_disk_client import YandexDiskClient



class SyncIgnore:
    """Класс для обработки .syncignore файлов (аналог .gitignore)"""
    
    def __init__(self, rules_text=""):
        self.rules = []
        self.parse_rules(rules_text)
    
    def parse_rules(self, rules_text:str):
        """Парсинг правил из текста .syncignore"""
        self.rules = []
        if not rules_text:
            return
            
        for line in rules_text.strip().split('\n'):
            line = line.strip()
            
            # Пропускаем пустые строки и комментарии
            if not line or line.startswith('#'):
                continue
            
            # Обрабатываем правило
            negate = line.startswith('!')
            if negate:
                line = line[1:]
                
            # Нормализуем путь (убираем ведущие слеши)
            if line.startswith('/'):
                line = line[1:]
                
            self.rules.append({
                'pattern': line,
                'negate': negate,
                'is_directory': line.endswith('/'),
                'absolute': not ('*' in line or '?' in line or '[' in line)
            })
    
    def should_ignore(self, file_path:str, is_directory:bool=False):
        """Проверить, нужно ли игнорировать файл/папку"""
        if not self.rules or not file_path:
            return False
            
        # Нормализуем путь
        path = file_path.replace('\\', '/').lstrip('/')
        
        ignored = False
        
        for rule in self.rules:
            pattern = rule['pattern']
            
            # Проверяем тип (файл/папка)
            if rule['is_directory'] and not is_directory:
                continue
                
            # Убираем слеш в конце для паттерна папки
            if pattern.endswith('/'):
                pattern = pattern[:-1]
            
            # Проверяем совпадение
            matched = False
            
            if rule['absolute']:
                # Точное совпадение
                matched = (path == pattern or path.startswith(pattern + '/'))
            else:
                # Используем fnmatch для паттернов
                # Проверяем полный путь и имя файла
                matched = (fnmatch.fnmatch(path, pattern) or 
                          fnmatch.fnmatch(os.path.basename(path), pattern))
                
                # Также проверяем, если файл находится в игнорируемой папке
                path_parts = path.split('/')
                for i in range(len(path_parts)):
                    subpath = '/'.join(path_parts[:i+1])
                    if fnmatch.fnmatch(subpath, pattern):
                        matched = True
                        break
            
            if matched:
                if rule['negate']:
                    ignored = False  # Отрицание - не игнорировать
                else:
                    ignored = True   # Игнорировать
                    
        return ignored


THREADS_COUNT = 16  # Снижено с 16 до 8 для стабильности API

class SyncProject:
    """ Класс для синхронизации отдельного проекта """
    syncignore: SyncIgnore
    yandex_disk_client: YandexDiskClient

    # Все просканированные обьекты
    sync_items: Dict[str, SyncItem] # {relative_path: SyncItem}

    # Файлы, наличествуют только локально
    items_need_for_update: Dict[str, Dict[str, List[SyncItem]]]

    def __init__(self, base_path: Path | str, category_name:str, project_name: str, token: str):
        """
        Инициализация синхронизатора отдельного проекта
        Args:
            local_path: Путь к локальной папке проекта
            cloud_path: Путь к удаленной папке проекта
            token: Токен для доступа к облаку
        """

        relative_path = os.path.join(category_name, project_name)

        self.yandex_disk_client = YandexDiskClient(token)
        self.syncignore = SyncIgnore()

        self.sync_items = {} 

        self.local_path = Path(base_path) / relative_path
        self.cloud_path = Path("app:") / relative_path
        self.relative_path = relative_path

        self.items_need_for_update = {
            'empty': {
                'empty': [],
                'file': [],
                'dir': [],
            },
            'file': {
                'empty': [],
                'file': [],
                'dir': [],
            },
            'dir': {
                'empty': [],
                'file': [],
                'dir': [],
            }
        }

    @property
    def token(self):
        return self.yandex_disk_client.token


    def __str__(self):
        """Строковое представление проекта"""
        return f"<{self.relative_path}>"


    def __repr__(self):
        """Подробное строковое представление проекта"""
        return f"<SyncProject {self.relative_path}>"


    def create_item(self, relative_path: str):
        if relative_path:
            return SyncItem(self.local_path / relative_path, self.cloud_path / relative_path, self.token)
        return SyncItem(self.local_path, self.cloud_path, self.token)


    def local_scan(self):

        root_dir = self.create_item("")
        root_dir.calc_local_state()

        if root_dir.local_type == 'empty':
            root_dir.create_local_dir()
        elif root_dir.local_type == 'file':
            raise FileExistsError(f'{root_dir} if file!')

        syncignore_file = self.create_item('.syncignore')
        syncignore_file.calc_local_state()

        if syncignore_file.local_type == 'empty':
            syncignore_file.local_path.touch()
            syncignore_file.local_path.write_text(".git\n")
            syncignore_file.local_type = 'file'
        elif syncignore_file.local_type == 'dir':
            raise FileExistsError(f'{syncignore_file} is dir!')

        # Считываем содержимое .syncignore и парсим правила
        syncignore_text = ""
        if syncignore_file.local_type == 'file':
            try:
                syncignore_text = syncignore_file.local_path.read_text(encoding='utf-8')
            except Exception as e:
                print(f"⚠️ Не удалось прочитать .syncignore: {e}")
        self.syncignore.parse_rules(syncignore_text)

        
        # Сначала быстро сканируем локальные файлы (SSD = мгновенно)
        print("🔍 Сканируем локальные файлы")
        local_start = time.time()
        self._scan_local_items("")
        local_time = time.time() - local_start
        print(f"  ✅ Локальные файлы просканированы за {local_time:.3f} сек")
        

    def cloud_scan(self):

        # Затем многопоточно сканируем удаленные файлы (API = узкое место)
        print("🔍 Многопоточное сканирование удаленных файлов (API)...")
        cloud_start = time.time()
        self._scan_cloud_items_parallel()
        cloud_time = time.time() - cloud_start
        print(f"  ✅ Удаленные файлы просканированы за {cloud_time:.3f} сек")
        
        for sync_item in self.sync_items.values():
            if sync_item.local_type != sync_item.cloud_type or sync_item.local_state.md5 != sync_item.cloud_state.md5: 
                self.items_need_for_update[sync_item.local_type][sync_item.cloud_type].append(sync_item)

        total_sync_objects = sum(
            len(items)
            for local_type_dict in self.items_need_for_update.values()
            for items in local_type_dict.values()
        )
        print(f"🔢 Всего обьектов: {len(self.sync_items)}")

        print(f"📊 Требуют синхронизации: {total_sync_objects}")
        print(f"⚡ Время сканирования по API: {cloud_time:.3f}с")


    def _scan_local_items(self, current_path: str):
        """Рекурсивно сканирует локальные файлы и папки"""
        local_dir_path = self.local_path / current_path
        
        if not local_dir_path.exists():
            return
            
        for item in local_dir_path.iterdir():
            relative_path = os.path.join(current_path, item.name) if current_path else item.name
            
            # Проверяем игнорирование
            if self.syncignore.should_ignore(relative_path, item.is_dir()):
                continue

            if relative_path not in self.sync_items:
                self.sync_items[relative_path] = self.create_item(relative_path)

            self.sync_items[relative_path].calc_local_state()

            if self.sync_items[relative_path].local_type == 'dir':
                self._scan_local_items(relative_path)


    def _scan_cloud_items_parallel(self):
        """Оптимизированное многопоточное сканирование удаленных файлов и папок"""
        print("    🚀 Начинаем оптимизированное многопоточное сканирование...")
        
        # Thread-safe доступ к общим словарям
        items_lock = threading.Lock()
        folders_queue_lock = threading.Lock()
        
        # Кэш уже просканированных папок (чтобы избежать дублирования)
        scanned_folders = set()
        folders_to_scan = []  # Очередь папок для сканирования
        
        def process_folder_items(folder_path, items):
            """Обрабатывает элементы папки и добавляет подпапки в очередь"""
            with folders_queue_lock:
                if folder_path in scanned_folders:
                    return  # Уже обработана
                scanned_folders.add(folder_path)
            
            subfolders_found = []
            
            for item in items:
                item_name = item['name']
                relative_path: str = os.path.join(folder_path, item_name) if folder_path else item_name

                is_dir = item['type'] == 'dir'

                # Проверяем игнорирование
                if self.syncignore.should_ignore(relative_path, is_dir):
                    continue
                
                if is_dir:

                    with items_lock:
                        if relative_path not in self.sync_items:
                            self.sync_items[relative_path] = self.create_item(relative_path)

                        self.sync_items[relative_path].cloud_state.from_dict(item)
                        # sync_item = self.sync_items[relative_path]
                        # sync_item.cloud_type = 'dir'

                    # Добавляем в очередь для сканирования
                    subfolders_found.append(relative_path)

                else:

                    with items_lock:
                        if relative_path not in self.sync_items:
                            self.sync_items[relative_path] = self.create_item(relative_path) 

                        self.sync_items[relative_path].cloud_state.from_dict(item)

            # Добавляем найденные подпапки в очередь
            with folders_queue_lock:
                for subfolder in subfolders_found:
                    if subfolder not in scanned_folders:
                        folders_to_scan.append(subfolder)
        
        def scan_single_folder(folder_path):
            """Сканирует одну папку и обрабатывает результаты"""
            try:
                items = self.yandex_disk_client.list(self.cloud_path / folder_path)
                process_folder_items(folder_path, items)
                return True
            except Exception as e:
                print(f"    ⚠️ Ошибка сканирования папки {folder_path}: {e}")
                return False
        
        # Начинаем с корневой папки
        folders_to_scan.append("")
        total_scanned = 0
        
        print("    ⚡ Запускаем адаптивное многопоточное сканирование...")
        
        # Итеративное сканирование с адаптивным количеством потоков
        while folders_to_scan:
            # Берем текущую порцию папок для сканирования
            with folders_queue_lock:
                current_batch = folders_to_scan[:]
                folders_to_scan.clear()
            
            if not current_batch:
                break
            
            max_workers = min(THREADS_COUNT, len(current_batch))
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Запускаем сканирование текущей порции
                futures = [executor.submit(scan_single_folder, folder) for folder in current_batch]
                
                # Ждем завершения
                for future in concurrent.futures.as_completed(futures):
                    try:
                        if future.result():
                            total_scanned += 1
                    except Exception as e:
                        print(f"    ❌ Ошибка в потоке: {e}")
            
            print(f"    📊 Просканировано папок: {total_scanned}")
        
        print(f"    ✅ Оптимизированное многопоточное сканирование завершено! Всего папок: {total_scanned}")


    def set_cache(self):
        """Создает кэш проекта на основе self.sync_items для быстрого доступа к информации о проекте"""
        print("📋 Создаем кэш проекта...")
        
        cache_data_files: Dict[str, dict] = {}
        cache_data_dirs: Dict[str, dict] = {}

        cache_data_statistics: Dict[str, int] = {
            "total_files": 0,
            "total_directories": 0,
            "total_size": 0,
        }

        cache_data = {
            "project_info": {
                "local_path": str(self.local_path),
                "cloud_path": str(self.cloud_path),
                "last_updated": datetime.datetime.now().isoformat(),
                "cache_version": "1.0"
            },
            "files": cache_data_files,
            "dirs": cache_data_dirs,
            "statistics": cache_data_statistics
        }
        

        total_size = 0
        
        # Обрабатываем все sync_items
        for relative_path, sync_item in self.sync_items.items():
                
            if sync_item.local_type == 'file':
                cache_data_files[relative_path] = sync_item.local_state.to_dict()
                total_size += sync_item.local_state.size

            elif sync_item.local_type == 'dir':
                cache_data_dirs[relative_path] = sync_item.local_state.to_dict()
                
        # Обновляем статистику
        cache_data_statistics["total_files"] = len(cache_data_files)
        cache_data_statistics["total_directories"] = len(cache_data_dirs)
        cache_data_statistics["total_size"] = total_size
        
        # Сохраняем кэш в файл
        cache_file_path = self.local_path / ".project_cache.json"
        try:
            with open(cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            print(f"  ✅ Кэш проекта создан: {cache_file_path}")
        except Exception as e:
            print(f"  ❌ Ошибка создания кэша: {e}")
    
    
    def get_cache(self) -> Optional[Dict]:
        """
        Читает и возвращает содержимое .project_cache.json
        
        Returns:
            Dict с данными кэша или None если файл не найден
        """
        cache_file = self.local_path / ".project_cache.json"
        
        if not cache_file.exists():
            return None
            
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Ошибка чтения кэша проекта {self.cloud_path}: {e}")
            return None
    

    def show_status(self):
        """
        Показывает детальную информацию о статусе проекта.
        
        Выводит:
        - Информацию о кэше (найден/отсутствует)
        - Список новых файлов и папок
        - Список удаленных файлов и папок  
        - Список измененных файлов с деталями
        - Рекомендации по дальнейшим действиям
        
        Примечание: Все файлы и папки фильтруются через .syncignore
        """
        print(f"\n📊 Статус проекта {str(self)}...")
        
        cache = self.get_cache()
        
        if not cache:
            print("❌ Кэш проекта отсутствует. Сохраните проект на облако для создания кэша")
            return
        
        print(f"✅ Кэш найден (обновлен: {cache['project_info']['last_updated']})")

        self.local_scan()

        # Получаем текущее состояние файловой системы
        cache_files = cache.get('files', {})
        cache_dirs = cache.get('dirs', {})
                
        current_files = {}
        current_dirs = {}
        
        current_total_size = 0

        for relative_path, sync_item in self.sync_items.items():
                
            if sync_item.local_type == 'file':
                current_files[relative_path] = sync_item.local_state.to_dict()
                current_total_size += sync_item.local_state.size

            elif sync_item.local_type == 'dir':
                current_dirs[relative_path] = sync_item.local_state.to_dict()

        # Анализируем изменения
        cache_files_set = set(cache_files.keys())
        current_files_set = set(current_files.keys())
        cache_dirs_set = set(cache_dirs.keys())
        current_dirs_set = set(current_dirs.keys())
        
        new_files = current_files_set - cache_files_set
        removed_files = cache_files_set - current_files_set
        new_dirs = current_dirs_set - cache_dirs_set
        removed_dirs = cache_dirs_set - current_dirs_set
        changed_files = set()
        
        # Проверяем изменения в существующих файлах
        for relative_path in cache_files_set & current_files_set:
            cache_file_info = cache_files[relative_path]
            current_file_info = current_files[relative_path]
            
            if cache_file_info.get('md5', '') != current_file_info.get('md5', ''):
                changed_files.add(relative_path)
        
        # Выводим результаты
        if not any([new_files, removed_files, new_dirs, removed_dirs, changed_files]):
            print("✅ Проект синхронизирован - изменений не обнаружено")
            return
        
        print("🔄 Обнаружены изменения:")
        
        if new_files:
            print(f"\n📁 Новые файлы ({len(new_files)}):")
            for file_path in sorted(new_files):
                size = current_files[file_path]['size']
                print(f"   + {file_path} ({size} B)")
        
        if removed_files:
            print(f"\n🗑️ Удаленные файлы ({len(removed_files)}):")
            for file_path in sorted(removed_files):
                size = cache_files[file_path]['size']
                print(f"   - {file_path} ({size} B)")
        
        if new_dirs:
            print(f"\n📂 Новые папки ({len(new_dirs)}):")
            for dir_path in sorted(new_dirs):
                print(f"   + {dir_path}/")
        
        if removed_dirs:
            print(f"\n🗑️ Удаленные папки ({len(removed_dirs)}):")
            for dir_path in sorted(removed_dirs):
                print(f"   - {dir_path}/")
        
        if changed_files:
            print(f"\n📝 Измененные файлы ({len(changed_files)}):")
            for file_path in sorted(changed_files):
                size = current_files[file_path]['size']
                print(f"   ~ {file_path} ({size} B)")
        
        print(f"\n💡 Сохраните проект на облако для синхронизации изменений")
    


    def sync_load(self):
        # Синхронизируем локальное состояние с облачным

        self.local_scan()
        self.cloud_scan()

        def async_remove_local(sync_item: SyncItem):
            sync_item.remove_local()

        self.multythread_operation(async_remove_local, 
                                   *self.items_need_for_update['file']['empty'],
                                   *self.items_need_for_update['file']['dir'], 
                                   *self.items_need_for_update['dir']['empty'],
                                   *self.items_need_for_update['dir']['file']
        ) 

        def async_create_dir_local(sync_item: SyncItem):
            sync_item.create_local_dir()

        self.multythread_operation(async_create_dir_local, 
                                *self.items_need_for_update['empty']['dir'],
                                *self.items_need_for_update['file']['dir']
        )


        def asafe_download_file(sync_item: SyncItem):
            sync_item.download_file()

        self.multythread_operation(asafe_download_file, 
                                *self.items_need_for_update['empty']['file'],
                                *self.items_need_for_update['dir']['file'],
                                *self.items_need_for_update['file']['file'],
        )


    def sync_save(self):
        print(f"⬆️ Начинаем сохранение проекта {str(self)}...")

        self.local_scan()
        
        # Создаем кэш проекта перед облачным сканированием
        self.set_cache()

        self.cloud_scan()

        def async_remove_cloud(sync_item: SyncItem):
            sync_item.remove_cloud()

        self.multythread_operation(async_remove_cloud, 
                                   *self.items_need_for_update['empty']['file'],
                                   *self.items_need_for_update['empty']['dir'], 
                                   *self.items_need_for_update['file']['dir'],
                                   *self.items_need_for_update['dir']['file']
        ) 

        def async_create_cloud_dir(sync_item: SyncItem):
            sync_item.create_cloud_dir()

        self.multythread_operation(async_create_cloud_dir, 
                                   *self.items_need_for_update['dir']['empty'],
                                   *self.items_need_for_update['dir']['file']
        )

        def async_upload_file(sync_item: SyncItem):
            sync_item.upload_file()

        self.multythread_operation(async_upload_file, 
                                   *self.items_need_for_update['file']['empty'],
                                   *self.items_need_for_update['file']['dir'], 
                                   *self.items_need_for_update['file']['file'],
        )


    def multythread_operation(self, handler: Callable, *items , reverse=False):
        
        if not items:
            return 

        max_workers = min(THREADS_COUNT, len(items))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: List[concurrent.futures.Future] = [executor.submit(handler, item) for item in sorted(items, key=lambda x:x.cloud_path, reverse=reverse)]
            
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                completed += 1
                if completed % THREADS_COUNT == 0 or completed == len(futures):
                    print(f"    📊 Обработано обьектов: {completed}/{len(futures)}")


if __name__ == "__main__":

    # Загружаем переменные окружения из .env файла
    load_dotenv()

    YANDEX_DISK_TOKEN = os.getenv("YANDEX_DISK_TOKEN")
    BASE_PATH = os.getenv("BASE_PATH")

    if not YANDEX_DISK_TOKEN or not BASE_PATH:
        print("❌ Не найдены необходимые переменные окружения YANDEX_DISK_TOKEN и/или BASE_PATH в .env файле.")
        sys.exit(1)

    # Базовая папка, относительно которой строится путь на Яндекс.Диске

    # Получаем абсолютный путь к текущей директории
    current_path = os.path.abspath(os.getcwd())

    # Проверяем, что мы находимся внутри base_path
    if not current_path.startswith(BASE_PATH):
        print(f"❌ Текущая папка '{current_path}' не находится внутри '{BASE_PATH}'")
        sys.exit(1)

    # Получаем относительный путь от base_path
    rel_to_base = os.path.relpath(current_path, BASE_PATH)
    parts = rel_to_base.split(os.sep)

    # Проверяем, что путь достаточно длинный (минимум Категория/Проект)
    if len(parts) < 2:
        print(f"❌ Скрипт должен запускаться из подпапки проекта внутри '{BASE_PATH}Категория/Проект/'.")
        sys.exit(1)

    # Определяем папку проекта (две директории выше)
    project_local_path = os.path.join(BASE_PATH, parts[0], parts[1])

    # Проверяем, что папка проекта действительно существует
    if not os.path.isdir(project_local_path):
        print(f"❌ Папка проекта '{project_local_path}' не найдена.")
        sys.exit(1)

    # Получаем относительный путь к проекту относительно base_path

    # Получаем название категории (папка, внутри которой находится папка проекта)
    category_name = parts[0]
    project_name = parts[1]
    relative_path = os.path.join(category_name, project_name)

    # Создаём экземпляр SyncProject с вычисленными путями
    project = SyncProject(
        Path(BASE_PATH),
        category_name,
        project_name,
        YANDEX_DISK_TOKEN
    )
    
    # Обработка командной строки: save (выгрузить в облако), load (загрузить из облака), status (показать статус)
    if len(sys.argv) < 2:
        print("❗ Укажите команду: save (выгрузить в облако), load (загрузить из облака) или status (показать статус)")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "save":
        print(f"⏫ Сохраняем изменения на Яндекс.Диск ({category_name})...")
        project.sync_save()
    elif command == "load":
        print(f"⏬ Загружаем изменения из Яндекс.Диска '{relative_path}'...")
        project.sync_load()
    elif command == "status":
        project.show_status()
    else:
        print(f"❌ Неизвестная команда: {command}. Используйте save, load или status.")
        sys.exit(1)
