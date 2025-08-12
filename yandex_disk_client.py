import requests
import time
import random
from pathlib import Path


class YandexDiskClient:
    """
    Клиент для работы с Яндекс.Диском через API.
    
    Основные возможности:
    - Универсальный HTTP клиент с retry механизмом и rate limiting
    - CRUD операции для файлов и папок
    - Автоматическая пагинация для больших списков
    - Специализированная обработка upload/download операций
    - Экспоненциальный backoff с jitter для стабильности
    
    Архитектурные особенности:
    - Разделение API вызовов и прямых HTTP запросов
    - Адаптивные timeout'ы в зависимости от типа операции
    - Детальное логирование с эмодзи для мониторинга
    """
    def _normalize_path(self, path: str | Path) -> Path:
        """
        Внутренний метод: приводит путь к типу Path, если передан str.
        """
        if isinstance(path, str):
            return Path(path)
        return path

    def __init__(self, token: str):
        self.token = token
        self.api_base = "https://cloud-api.yandex.net/v1/disk/resources"
        self.headers = {"Authorization": f"OAuth {self.token}"}

    def _make_request(self, method: str, url: str="/", params=None, max_retries: int = 3, is_api_call: bool = True, **kwargs):
        """
        Универсальный HTTP запрос с механизмом повторных попыток
        
        Args:
            method: HTTP метод (GET, POST, PUT, DELETE)
            url: URL endpoint (для API) или полный URL (для upload/download)
            max_retries: Максимальное количество повторных попыток
            is_api_call: True для API вызовов (добавляет base URL + headers), False для прямых HTTP
            **kwargs: Дополнительные параметры для requests
            
        Returns:
            Response объект или None при критической ошибке
        """

        # Преобразуем значения params из Path в str, если нужно
        if params is not None and isinstance(params, dict):
            params = {k: str(v) if isinstance(v, Path) else v for k, v in params.items()}
            kwargs['params'] = params

        # Типы ошибок, которые стоит повторять
        retryable_errors = (
            requests.exceptions.ConnectionError,    # Network is unreachable
            requests.exceptions.Timeout,            # Timeout errors
            requests.exceptions.ChunkedEncodingError,  # Incomplete read
            requests.exceptions.HTTPError           # HTTP errors
        )
        
        for attempt in range(max_retries + 1):
            try:
                # Добавляем timeout для предотвращения зависания
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = 60 if not is_api_call else 30  # Увеличенный timeout для upload/download
                
                # Определяем URL и headers в зависимости от типа запроса
                if is_api_call:
                    full_url = self.api_base + url
                    request_headers = self.headers
                    operation_type = "API"
                else:
                    full_url = url
                    request_headers = kwargs.pop('headers', {})  # Для upload/download headers могут быть в kwargs
                    operation_type = "Upload/Download"
                
                response = requests.request(method, full_url, headers=request_headers, **kwargs)
                
                # Проверяем статус коды, которые стоит повторить
                if response.status_code == 429:  # Too Many Requests
                    if attempt < max_retries:
                        try:
                            retry_after = int(response.headers.get('Retry-After', '1'))
                        except (ValueError, TypeError):
                            retry_after = 1
                        wait_time = min(retry_after, 60)  # Максимум 60 секунд
                        print(f"🕐 {operation_type} rate limit (429), ждем {wait_time}с... (попытка {attempt + 1}/{max_retries + 1})")
                        time.sleep(wait_time)
                        continue
                
                if response.status_code >= 500:  # Server errors
                    if attempt < max_retries:
                        server_wait_time: float = self._calculate_backoff_time(attempt)
                        print(f"🔄 {operation_type} серверная ошибка {response.status_code}, повтор через {server_wait_time:.1f}с... (попытка {attempt + 1}/{max_retries + 1})")
                        time.sleep(server_wait_time)
                        continue
                
                # print(f'<{method}:{url}{kwargs.get("params", {})} -> {response.status_code}>')
                return response
                
            except retryable_errors as e:
                if attempt < max_retries:
                    network_wait_time: float = self._calculate_backoff_time(attempt)
                    print(f"🔄 {operation_type} сетевая ошибка: {type(e).__name__}, повтор через {network_wait_time:.1f}с... (попытка {attempt + 1}/{max_retries + 1})")
                    time.sleep(network_wait_time)
                    continue
                else:
                    print(f"❌ Критическая {operation_type.lower()} ошибка после {max_retries} попыток: {e}")
                    return None
                    
            except requests.exceptions.RequestException as e:
                # Некритичные ошибки, которые не стоит повторять
                print(f"❌ Ошибка {operation_type.lower()} запроса: {e}")
                return None
        
        # Если дошли сюда, значит все попытки исчерпаны
        print(f"❌ Исчерпаны все {max_retries} попытки для {method} {url}")
        return None
    
    def _calculate_backoff_time(self, attempt: int) -> float:
        """
        Рассчитывает время ожидания с экспоненциальным backoff + jitter
        
        Args:
            attempt: Номер попытки (0, 1, 2, ...)
            
        Returns:
            Время ожидания в секундах
        """
        # Экспоненциальный backoff: 1s, 2s, 4s, 8s...
        base_delay = min(2 ** attempt, 32)  # Максимум 32 секунды
        
        # Добавляем jitter (случайность) для избежания thundering herd
        jitter = random.uniform(0.1, 0.5) * base_delay
        
        return base_delay + jitter
    
    def _upload_file_with_retry(self, upload_url: str, local_path: str|Path, max_retries: int = 7):
        """
        Специализированная загрузка файла с retry механизмом.
        
        Отличается от _make_request:
        - Увеличенный timeout (120с) для больших файлов
        - Корректная обработка повторного чтения файла при retry
        - Больше попыток (7) для upload операций
        
        Args:
            upload_url: URL для загрузки файла (полученный через /upload)
            local_path: Путь к локальному файлу
            max_retries: Максимальное количество повторных попыток (по умолчанию 7)
            
        Returns:
            Response объект или None при критической ошибке
        """
        local_path = self._normalize_path(local_path)

        # Типы ошибок, которые стоит повторять
        retryable_errors = (
            requests.exceptions.ConnectionError,    # Network is unreachable
            requests.exceptions.Timeout,            # Timeout errors  
            requests.exceptions.ChunkedEncodingError,  # Incomplete read
            requests.exceptions.HTTPError           # HTTP errors
        )
        
        for attempt in range(max_retries + 1):
            try:
                # При каждой попытке заново открываем файл
                with open(local_path, "rb") as f:
                    response = requests.put(upload_url, files={"file": f}, timeout=120)  # Увеличенный timeout для upload
                
                # Проверяем статус коды, которые стоит повторить
                if response.status_code == 429:  # Too Many Requests
                    if attempt < max_retries:
                        try:
                            retry_after = int(response.headers.get('Retry-After', '1'))
                        except (ValueError, TypeError):
                            retry_after = 1
                        wait_time = min(retry_after, 60)  # Максимум 60 секунд
                        print(f"🕐 Upload rate limit (429), ждем {wait_time}с... (попытка {attempt + 1}/{max_retries + 1})")
                        time.sleep(wait_time)
                        continue
                
                if response.status_code >= 500:  # Server errors
                    if attempt < max_retries:
                        server_wait_time: float = self._calculate_backoff_time(attempt)
                        print(f"🔄 Upload серверная ошибка {response.status_code}, повтор через {server_wait_time:.1f}с... (попытка {attempt + 1}/{max_retries + 1})")
                        time.sleep(server_wait_time)
                        continue
                
                return response
                
            except retryable_errors as e:
                if attempt < max_retries:
                    network_wait_time: float = self._calculate_backoff_time(attempt)
                    print(f"🔄 Upload сетевая ошибка: {type(e).__name__}, повтор через {network_wait_time:.1f}с... (попытка {attempt + 1}/{max_retries + 1})")
                    time.sleep(network_wait_time)
                    continue
                else:
                    print(f"❌ Критическая Upload ошибка после {max_retries} попыток: {e}")
                    return None
                    
            except requests.exceptions.RequestException as e:
                # Некритичные ошибки, которые не стоит повторять
                print(f"❌ Ошибка Upload запроса: {e}")
                return None
        
        # Если дошли сюда, значит все попытки исчерпаны
        print(f"❌ Исчерпаны все {max_retries} попытки для upload {upload_url}")
        return None

    def list(self, cloud_path: str|Path, limit: int = 10000):
        """
        Получить полный список файлов и папок с автоматической пагинацией.
        
        Автоматически обрабатывает большие папки, получая все элементы
        через несколько API вызовов. Показывает прогресс для папок >1000 элементов.
        
        Args:
            cloud_path: Путь к папке в облаке
            limit: Максимальное количество элементов на страницу (максимум 10000)
            
        Returns:
            Полный список всех элементов в папке (файлы + папки)
            
        Note:
            Для больших папок (>1000 элементов) выводит прогресс в консоль
        """
        cloud_path = self._normalize_path(cloud_path)

        all_items = []
        offset = 0
        
        # Ограничиваем limit максимумом API
        page_limit = min(limit, 10000)
        
        while True:
            params = {
                "path": str(cloud_path),
                "limit": page_limit,
                "offset": offset
            }
            
            response = self._make_request("GET", "/", params=params)
            if not response or response.status_code != 200:
                break
                
            data = response.json()
            embedded = data.get("_embedded", {})
            items = embedded.get("items", [])
            
            if not items:
                break  # Больше элементов нет
            
            all_items.extend(items)
            
            # Проверяем, получили ли все элементы
            total = embedded.get("total", 0)
            current_count = len(all_items)
            
            # Для больших папок показываем прогресс
            if total > 1000:
                print(f"  📄 Получено элементов: {current_count}/{total}")
            
            # Если получили все элементы или достигли лимита страницы
            if current_count >= total or len(items) < page_limit:
                break
                
            # Переходим к следующей странице
            offset += len(items)
        
        # Показываем итог только для больших папок
        if len(all_items) > 100:
            print(f"  ✅ Итого элементов получено: {len(all_items)}")
        return all_items

    def exists(self, cloud_path: str|Path):
        """Проверить, существует ли файл или папка"""
        cloud_path = self._normalize_path(cloud_path)

        params = {"path": str(cloud_path), "fields": "path,type,name"}
        response = self._make_request("GET", "/", params=params)
        return response is not None and response.status_code == 200

    def get_item_state(self, cloud_path: str|Path):
        """Получить информацию о файле/папке или None если не существует"""
        cloud_path = self._normalize_path(cloud_path)

        params = {"path": str(cloud_path), "fields": "name,type,size,md5,modified"}
        response = self._make_request("GET", "/", params=params)
        
        if response and response.status_code == 200:
            return response.json()
        return None

    def create_dir(self, cloud_path: str|Path, create_parent=True):
        """Создать папку"""
        cloud_path = self._normalize_path(cloud_path)

        params = {"path": cloud_path}
        response = self._make_request("PUT", "/", params=params)

        if response.status_code == 201:
            print(f"📁 Папка создана: {cloud_path}")
            return True
        elif response.status_code == 409:
            if self.exists(cloud_path):
                print(f"📁 Папка уже существует: {cloud_path}")
                return True
            elif create_parent:
                cloud_path_parent = cloud_path.parent
                return self.create_dir(cloud_path_parent) and self.create_dir(cloud_path, create_parent=False)
        print(f"❌ Не удалось создать папку: {cloud_path}, {response}")
        return False

    def remove(self, cloud_path: str|Path, permanently: bool = True):
        """Удалить файл или папку"""
        cloud_path = self._normalize_path(cloud_path)

        params = {"path": str(cloud_path), "permanently": str(permanently).lower()}
        response = self._make_request("DELETE", "/", params=params)
        if response and response.status_code in (202, 204):
            print(f"🗑️  Удалено: {cloud_path}")
            return True
        print(f"❌ Не удалось удалить: {cloud_path}")
        return False

    def download(self, local_path: str|Path, cloud_path: str|Path):
        """Скачать файл с Яндекс.Диска"""

        cloud_path = self._normalize_path(cloud_path)

        params = {"path": str(cloud_path)}
        response = self._make_request("GET", "/download", params=params)
        if not response:
            print(f"❌ Не удалось получить ссылку для скачивания: {cloud_path}")
            return False
        try:
            download_url = response.json()["href"]
            # Используем универсальный retry механизм для download URL
            r = self._make_request("GET", download_url, is_api_call=False)
            if r and r.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(r.content)
                print(f"⬇️  Скачан: {cloud_path}")
                return True
            else:
                print(f"❌ Ошибка скачивания: {cloud_path} (статус: {r.status_code if r else 'None'})")
                return False
        except Exception as e:
            print(f"❌ Ошибка при скачивании файла {cloud_path}: {e}")
            return False


    def upload(self, local_path: str|Path, cloud_path: str|Path, overwrite: bool = True, create_parent=True):
        """Загрузить файл на Яндекс.Диск"""

        local_path = self._normalize_path(local_path)
        cloud_path = self._normalize_path(cloud_path)

        params = {"path": cloud_path, "overwrite": str(overwrite).lower()}
        response = self._make_request("GET", "/upload", params=params)
        if not response:
            if response.status_code == 409:
                cloud_path_parent = cloud_path.parent

                if create_parent and self.create_dir(cloud_path_parent):
                    return self.upload(local_path, cloud_path, overwrite=overwrite, create_parent=False)
            print(f"❌ Не удалось получить ссылку для загрузки: {cloud_path}")
            return False
        try:
            upload_url = response.json()["href"]
            r = self._upload_file_with_retry(upload_url, local_path)
            if r and r.status_code in (201, 202):
                print(f"⬆️  Загружен: {cloud_path}")
                return True
            else:
                print(f"❌ Ошибка загрузки: {cloud_path} (статус: {r.status_code if r else 'None'})")
                return False
        except Exception as e:
            print(f"❌ Ошибка при загрузке файла {cloud_path}: {e}")
            return False


    def move(self, from_cloud_path: str|Path, to_cloud_path: str|Path, overwrite: bool = True):
        """Переместить файл или папку"""
        from_cloud_path = self._normalize_path(from_cloud_path)
        to_cloud_path = self._normalize_path(to_cloud_path)

        params = {
            "from": str(from_cloud_path),
            "path": str(to_cloud_path),
            "overwrite": str(overwrite).lower()
        }
        response = self._make_request("POST", "/move", params=params)
        if response and response.status_code in (201, 202):
            print(f"🚚 Перемещено: {from_cloud_path} → {to_cloud_path}")
            return True
        print(f"❌ Не удалось переместить: {from_cloud_path} → {to_cloud_path}")
        return False


    def copy(self, from_cloud_path: str|Path, to_cloud_path: str|Path, overwrite: bool = True):
        """Скопировать файл или папку"""
        from_cloud_path = self._normalize_path(from_cloud_path)
        to_cloud_path = self._normalize_path(to_cloud_path)

        params = {
            "from": str(from_cloud_path),
            "path": str(to_cloud_path),
            "overwrite": str(overwrite).lower()
        }
        response = self._make_request("POST", "/copy", params=params)
        if response and response.status_code in (201, 202):
            print(f"📄 Скопировано: {from_cloud_path} → {to_cloud_path}")
            return True
        print(f"❌ Не удалось скопировать: {from_cloud_path} → {to_cloud_path}")
        return False


if __name__ == "__main__":
    # main() 

    client = YandexDiskClient("y0__xCPzsuMAhiYnTkg35nf-BM948LQog9swbmNQT8rEa-gt1Alwg")

    # client.upload("test2/test3/testfile")
    print(len(client.list('app:/TestCategory/ArticleFullWaveSeis/.git/objects')))
    