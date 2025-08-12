#!/usr/bin/env python3
"""
Интеграционный тест для sync_project.py

Тестирует полный цикл синхронизации:
1. Отправка test_project в облако (save)
2. Загрузка test_project из облака (load)
3. Проверка статуса синхронизации

Для запуска требуется:
- .env файл с YANDEX_DISK_TOKEN и BASE_PATH
- test_project папка в рабочей директории
"""

import os
import sys
import time
import shutil
from pathlib import Path
from typing import Optional
from unittest.mock import patch
import subprocess
from dotenv import load_dotenv


class SyncProjectIntegrationTest:
    """Интеграционный тест для sync_project.py"""
    
    def __init__(self):
        # Загружаем переменные окружения
        load_dotenv()
        
        self.yandex_token = os.getenv("YANDEX_DISK_TOKEN")
        self.base_path = os.getenv("BASE_PATH")
        
        if not self.yandex_token or not self.base_path:
            raise ValueError("Не найдены YANDEX_DISK_TOKEN или BASE_PATH в .env файле")
        
        # Пути для тестирования
        self.workspace_path = Path.cwd()
        print(f'workspace_path: {self.workspace_path}')
        self.test_project_path = self.workspace_path / "tests"/ "test_project"
        self.tmp_category_path: Optional[Path] = None
        
        # Проверяем наличие test_project
        if not self.test_project_path.exists():
            raise FileNotFoundError(f"Папка test_project не найдена в {self.workspace_path}")
    
    def setup(self):
        """Подготовка к тестированию"""
        print("🔧 Подготовка к интеграционному тесту...")
        
        # Создаем временную папку для тестирования прямо внутри BASE_PATH
        if self.base_path is None:
            raise RuntimeError("base_path не инициализирован")
        base_path = Path(self.base_path)
        temp_category_name = f"tmp_TestCategory_{int(time.time())}"
        self.tmp_category_path = base_path / temp_category_name
        self.tmp_category_path.mkdir(exist_ok=True)
        print(f"📁 Создана временная папка: {self.tmp_category_path}")
        
        # Создаем структуру папок: $BASE_PATH/tmp_TestCategory_xxx/test_project
        
        self.tmp_project_path = self.tmp_category_path / "test_project"
        shutil.copytree(self.test_project_path, self.tmp_project_path)
        print(f"📋 Скопирован test_project в {self.tmp_project_path}")
        
        # Переходим в папку проекта (должно быть на две директории выше от BASE_PATH)
        os.chdir(self.tmp_project_path)
        print(f"📍 Перешли в рабочую директорию: {self.tmp_project_path}")
        
    
    def teardown(self):
        """Очистка после тестирования"""
        print("🧹 Очистка после тестирования...")
        
        # Возвращаемся в исходную директорию
        os.chdir(self.workspace_path)
        
        # # Удаляем временную папку
        # if self.tmp_category_path and self.tmp_category_path.exists():
        #     shutil.rmtree(self.tmp_category_path)
        #     print(f"🗑️ Удалена временная папка: {self.tmp_category_path}")
    
    def run_sync_command(self, command, project_name="test_project"):
        """Запускает команду sync_project.py"""
        print(f"🚀 Запуск команды: {command}")
        
        if self.tmp_category_path is None:
            raise RuntimeError("backup_path не инициализирован")
        
        # Переходим в папку проекта (tmp_TestCategory_xxx/test_project)
        if not self.tmp_project_path.exists():
            raise FileNotFoundError(f"Проект {project_name} не найден в {self.tmp_project_path}")
        
        os.chdir(self.tmp_project_path)
        
        # Запускаем команду
        try:
            result = subprocess.run(
                [sys.executable, str(self.workspace_path / "sync_project.py"), command],
                capture_output=True,
                text=True,
                timeout=300  # 5 минут таймаут
            )
            
            print(f"📤 Команда {command} завершена с кодом: {result.returncode}")
            if result.stdout:
                print("📋 Вывод:")
                print(result.stdout)
            if result.stderr:
                print("⚠️ Ошибки:")
                print(result.stderr)
            
            return result
            
        except subprocess.TimeoutExpired:
            print(f"⏰ Команда {command} превысила таймаут (5 минут)")
            return None
        except Exception as e:
            print(f"❌ Ошибка выполнения команды {command}: {e}")
            return None
    
    def test_full_sync_cycle(self):
        """Тестирует полный цикл синхронизации"""
        print("\n" + "="*60)
        print("🔄 ТЕСТ ПОЛНОГО ЦИКЛА СИНХРОНИЗАЦИИ")
        print("="*60)
        
        try:
            # Шаг 1: Отправляем проект в облако
            print("\n📤 ШАГ 1: Отправка test_project в облако...")
            save_result = self.run_sync_command("save")
            
            if not save_result or save_result.returncode != 0:
                print("❌ Ошибка при отправке проекта в облако")
                return False
            
            print("✅ Проект успешно отправлен в облако")
            
            # Небольшая пауза для стабилизации API
            print("⏳ Пауза 10 секунд для стабилизации API...")
            time.sleep(10)
            
            # Шаг 2: Проверяем статус
            print("\n📊 ШАГ 2: Проверка статуса синхронизации...")
            status_result = self.run_sync_command("status")
            
            if not status_result or status_result.returncode != 0:
                print("❌ Ошибка при проверке статуса")
                return False
            
            print("✅ Статус синхронизации получен")
            
            # Шаг 3: Загружаем проект из облака
            print("\n📥 ШАГ 3: Загрузка test_project из облака...")
            
            # Сначала удаляем локальную папку проекта
            if self.tmp_category_path is None:
                raise RuntimeError("backup_path не инициализирован")
            if self.tmp_project_path.exists():
                shutil.rmtree(self.tmp_project_path)
                print("🗑️ Локальная папка test_project удалена")
            
            # Создаем новую папку проекта
            self.tmp_project_path.mkdir(parents=True)
            print("📁 Создана новая папка test_project")
            
            # Загружаем из облака
            load_result = self.run_sync_command("load")
            
            if not load_result or load_result.returncode != 0:
                print("❌ Ошибка при загрузке проекта из облака")
                return False
            # Сравниваем загруженный проект с оригиналом
            print("\n🔎 Сравнение восстановленного проекта с оригиналом...")

            import filecmp

            def compare_dirs(dir1, dir2, ignore=None):
                """Рекурсивное сравнение двух директорий"""
                cmp = filecmp.dircmp(dir1, dir2, ignore=ignore)
                if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
                    print(f"❌ Отличия найдены между {dir1} и {dir2}:")
                    if cmp.left_only:
                        print(f"  Только в {dir1}: {cmp.left_only}")
                    if cmp.right_only:
                        print(f"  Только в {dir2}: {cmp.right_only}")
                    if cmp.diff_files:
                        print(f"  Различающиеся файлы: {cmp.diff_files}")
                    if cmp.funny_files:
                        print(f"  Проблемные файлы: {cmp.funny_files}")
                    return False
                # Рекурсивно сравниваем поддиректории
                for subdir in cmp.common_dirs:
                    if not compare_dirs(
                        dir1 / subdir,
                        dir2 / subdir,
                        ignore=ignore
                    ):
                        return False
                return True

            # Оригинальный проект
            orig_path = self.test_project_path
            # Восстановленный проект
            restored_path = self.tmp_project_path

            # Игнорируем .git и .syncignore для корректности
            ignore_list = [".git", ".syncignore", "__pycache__"]

            if compare_dirs(orig_path, restored_path, ignore=ignore_list):
                print("✅ Восстановленный проект идентичен оригиналу (за исключением игнорируемых файлов)")
            else:
                print("❌ Восстановленный проект отличается от оригинала")
                return False
            print("✅ Проект успешно загружен из облака")
            
            # Шаг 4: Финальная проверка статуса
            print("\n📊 ШАГ 4: Финальная проверка статуса...")
            final_status_result = self.run_sync_command("status")
            
            if not final_status_result or final_status_result.returncode != 0:
                print("❌ Ошибка при финальной проверке статуса")
                return False
            
            print("✅ Финальная проверка статуса завершена")
            
            print("\n🎉 ТЕСТ ПОЛНОГО ЦИКЛА СИНХРОНИЗАЦИИ УСПЕШНО ЗАВЕРШЕН!")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка во время тестирования: {e}")
            return False
    
    def test_sync_ignore_functionality(self):
        """Тестирует функциональность .syncignore"""
        print("\n" + "="*60)
        print("🚫 ТЕСТ ФУНКЦИОНАЛЬНОСТИ .SYNCIGNORE")
        print("="*60)
        
        try:
            # Проверяем наличие .syncignore файла
            if self.tmp_project_path is None:
                raise RuntimeError("backup_path не инициализирован")
            syncignore_path = self.tmp_project_path / ".syncignore"
            if not syncignore_path.exists():
                print("❌ .syncignore файл не найден")
                return False
            
            # Читаем содержимое .syncignore
            with open(syncignore_path, 'r') as f:
                syncignore_content = f.read()
            
            print(f"📄 Содержимое .syncignore:\n{syncignore_content}")
            
            # Проверяем, что .git папка игнорируется
            if ".git" in syncignore_content:
                print("✅ .git папка добавлена в .syncignore")
            else:
                print("⚠️ .git папка не найдена в .syncignore")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка при тестировании .syncignore: {e}")
            return False
    
    def run_all_tests(self):
        """Запускает все тесты"""
        print("🧪 ЗАПУСК ИНТЕГРАЦИОННЫХ ТЕСТОВ ДЛЯ SYNC_PROJECT.PY")
        print("="*80)
        
        try:
            self.setup()
            
            # Запускаем тесты
            test_results = []
            
            # Тест .syncignore
            test_results.append(("Функциональность .syncignore", self.test_sync_ignore_functionality()))
            
            # Тест полного цикла синхронизации
            test_results.append(("Полный цикл синхронизации", self.test_full_sync_cycle()))
            
            # Выводим результаты
            print("\n" + "="*80)
            print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
            print("="*80)
            
            all_passed = True
            for test_name, result in test_results:
                status = "✅ ПРОЙДЕН" if result else "❌ ПРОВАЛЕН"
                print(f"{test_name}: {status}")
                if not result:
                    all_passed = False
            
            if all_passed:
                print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
            else:
                print("\n⚠️ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ")
            
            return all_passed
            
        except Exception as e:
            print(f"❌ Критическая ошибка во время тестирования: {e}")
            return False
        finally:
            self.teardown()


def main():
    """Главная функция для запуска тестов"""
    try:
        test_runner = SyncProjectIntegrationTest()
        success = test_runner.run_all_tests()
        
        if success:
            print("\n🎯 ИНТЕГРАЦИОННЫЕ ТЕСТЫ ЗАВЕРШЕНЫ УСПЕШНО!")
            sys.exit(0)
        else:
            print("\n💥 ИНТЕГРАЦИОННЫЕ ТЕСТЫ ЗАВЕРШЕНЫ С ОШИБКАМИ!")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 