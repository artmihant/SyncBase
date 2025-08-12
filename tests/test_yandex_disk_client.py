#!/usr/bin/env python3
"""
Автотесты для YandexDiskClient (исправленная версия)

Тестирует новую функциональность с полным мокированием HTTP запросов:
- Универсальный HTTP клиент с retry
- Rate limiting обработку
- Специализированную загрузку файлов
- Автоматическую пагинацию
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import time
import requests
from pathlib import Path
import tempfile
import os

from yandex_disk_client import YandexDiskClient




class TestYandexDiskClient(unittest.TestCase):
    """Тесты для YandexDiskClient"""

    def setUp(self):
        """Подготовка к тестам"""
        self.token = "test_token"
        self.client = YandexDiskClient(self.token)
        
    def test_init(self):
        """Тест инициализации клиента"""
        self.assertEqual(self.client.token, self.token)
        self.assertEqual(self.client.api_base, "https://cloud-api.yandex.net/v1/disk/resources")
        self.assertEqual(self.client.headers, {"Authorization": f"OAuth {self.token}"})

    @patch('requests.request')
    def test_make_request_success(self, mock_request):
        """Тест успешного HTTP запроса"""
        # Подготавливаем мок
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"test": "data"}
        mock_request.return_value = mock_response
        
        # Выполняем запрос
        response = self.client._make_request("GET", "/test", is_api_call=True)
        
        # Проверяем результат
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        mock_request.assert_called_once()

    @patch('requests.request')
    def test_make_request_rate_limit_retry(self, mock_request):
        """Тест обработки rate limiting (429) с retry"""
        # Первый вызов возвращает 429, второй - 200
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "2"}
        
        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        
        mock_request.side_effect = [mock_response_429, mock_response_200]
        
        # Выполняем запрос
        response = self.client._make_request("GET", "/test", max_retries=3)
        
        # Проверяем результат
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_request.call_count, 2)

    @patch('requests.request')
    def test_make_request_server_error_retry(self, mock_request):
        """Тест обработки серверных ошибок (5xx) с retry"""
        # Первый вызов возвращает 500, второй - 200
        mock_response_500 = Mock()
        mock_response_500.status_code = 500
        
        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        
        mock_request.side_effect = [mock_response_500, mock_response_200]
        
        # Выполняем запрос
        response = self.client._make_request("GET", "/test", max_retries=3)
        
        # Проверяем результат
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_request.call_count, 2)

    @patch('requests.request')
    def test_make_request_connection_error_retry(self, mock_request):
        """Тест обработки сетевых ошибок с retry"""
        # Первый вызов вызывает ConnectionError, второй - успех
        mock_request.side_effect = [
            requests.exceptions.ConnectionError("Network error"),
            Mock(status_code=200)
        ]
        
        # Выполняем запрос
        response = self.client._make_request("GET", "/test", max_retries=3)
        
        # Проверяем результат
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_request.call_count, 2)

    @patch('requests.request')
    def test_make_request_max_retries_exceeded(self, mock_request):
        """Тест исчерпания максимального количества попыток"""
        # Все попытки возвращают 500
        mock_response = Mock()
        mock_response.status_code = 500
        mock_request.return_value = mock_response
        
        # Выполняем запрос
        response = self.client._make_request("GET", "/test", max_retries=2)
        
        # Проверяем результат
        self.assertIsNotNone(response)  # Метод возвращает последний response, а не None
        self.assertEqual(response.status_code, 500)
        self.assertEqual(mock_request.call_count, 3)  # 2 retry + 1 initial

    def test_calculate_backoff_time(self):
        """Тест расчета времени ожидания с backoff"""
        # Тестируем экспоненциальный рост
        times = []
        for attempt in range(5):
            wait_time = self.client._calculate_backoff_time(attempt)
            times.append(wait_time)
        
        # Проверяем, что время растет экспоненциально
        self.assertLess(times[0], times[1])
        self.assertLess(times[1], times[2])
        self.assertLess(times[2], times[3])
        
        # Проверяем, что время не превышает максимум (32 + jitter)
        for wait_time in times:
            self.assertLess(wait_time, 50)  # 32 + максимальный jitter

    @patch('requests.put')
    def test_upload_file_with_retry_success(self, mock_put):
        """Тест успешной загрузки файла"""
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_file_path = temp_file.name
        
        try:
            # Подготавливаем мок
            mock_response = Mock()
            mock_response.status_code = 201
            mock_put.return_value = mock_response
            
            # Выполняем загрузку
            response = self.client._upload_file_with_retry("http://upload.url", Path(temp_file_path))
            
            # Проверяем результат
            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 201)
            mock_put.assert_called_once()
            
        finally:
            # Удаляем временный файл
            os.unlink(temp_file_path)

    @patch('requests.put')
    def test_upload_file_with_retry_rate_limit(self, mock_put):
        """Тест обработки rate limiting при загрузке файла"""
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_file_path = temp_file.name
        
        try:
            # Первый вызов возвращает 429, второй - 201
            mock_response_429 = Mock()
            mock_response_429.status_code = 429
            mock_response_429.headers = {"Retry-After": "1"}
            
            mock_response_201 = Mock()
            mock_response_201.status_code = 201
            
            mock_put.side_effect = [mock_response_429, mock_response_201]
            
            # Выполняем загрузку
            response = self.client._upload_file_with_retry("http://upload.url", temp_file_path)
            
            # Проверяем результат
            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(mock_put.call_count, 2)
            
        finally:
            # Удаляем временный файл
            os.unlink(temp_file_path)

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    def test_list_single_page(self, mock_make_request):
        """Тест получения списка файлов (одна страница)"""
        # Подготавливаем мок ответа
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "_embedded": {
                "items": [
                    {"name": "file1.txt", "type": "file"},
                    {"name": "folder1", "type": "dir"}
                ],
                "total": 2
            }
        }
        mock_make_request.return_value = mock_response
        
        # Выполняем запрос
        items = self.client.list("/test")
        
        # Проверяем результат
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "file1.txt")
        self.assertEqual(items[1]["name"], "folder1")
        mock_make_request.assert_called_once()

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    def test_list_multiple_pages(self, mock_make_request):
        """Тест получения списка файлов (несколько страниц)"""
        # Подготавливаем моки для двух страниц
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = {
            "_embedded": {
                "items": [{"name": f"file{i}.txt", "type": "file"} for i in range(3)],
                "total": 5
            }
        }
        
        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = {
            "_embedded": {
                "items": [{"name": f"file{i}.txt", "type": "file"} for i in range(3, 5)],
                "total": 5
            }
        }
        
        mock_make_request.side_effect = [mock_response1, mock_response2]
        
        # Выполняем запрос
        items = self.client.list(Path("/test"), limit=3)
        
        # Проверяем результат
        self.assertEqual(len(items), 5)
        self.assertEqual(mock_make_request.call_count, 2)

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    def test_exists_true(self, mock_make_request):
        """Тест проверки существования файла (существует)"""
        # Подготавливаем мок
        mock_response = Mock()
        mock_response.status_code = 200
        mock_make_request.return_value = mock_response
        
        # Выполняем проверку
        exists = self.client.exists(Path("/test.txt"))
        
        # Проверяем результат
        self.assertTrue(exists)

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    def test_exists_false(self, mock_make_request):
        """Тест проверки существования файла (не существует)"""
        # Подготавливаем мок
        mock_response = Mock()
        mock_response.status_code = 404
        mock_make_request.return_value = mock_response
        
        # Выполняем проверку
        exists = self.client.exists(Path("/test.txt"))
        
        # Проверяем результат
        self.assertFalse(exists)

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    def test_create_dir_success(self, mock_make_request):
        """Тест успешного создания папки"""
        # Подготавливаем мок
        mock_response = Mock()
        mock_response.status_code = 201
        mock_make_request.return_value = mock_response
        
        # Выполняем создание
        result = self.client.create_dir("/test_folder")
        
        # Проверяем результат
        self.assertTrue(result)
        mock_make_request.assert_called_once()

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    def test_remove_success(self, mock_make_request):
        """Тест успешного удаления файла"""
        # Подготавливаем мок
        mock_response = Mock()
        mock_response.status_code = 202
        mock_make_request.return_value = mock_response
        
        # Выполняем удаление
        result = self.client.remove(Path("/test.txt"))
        
        # Проверяем результат
        self.assertTrue(result)
        mock_make_request.assert_called_once()

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    def test_download_success(self, mock_make_request):
        """Тест успешного скачивания файла"""
        # Создаем временный файл для скачивания
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file_path = temp_file.name
        
        try:
            # Мок для получения ссылки на скачивание
            mock_response1 = Mock()
            mock_response1.status_code = 200
            mock_response1.json.return_value = {"href": "http://download.url"}
            
            # Мок для самого скачивания
            mock_response2 = Mock()
            mock_response2.status_code = 200
            mock_response2.content = b"downloaded content"
            
            mock_make_request.side_effect = [mock_response1, mock_response2]
            
            # Выполняем скачивание
            result = self.client.download(temp_file_path, "/test.txt")
            
            # Проверяем результат
            self.assertTrue(result)
            self.assertEqual(mock_make_request.call_count, 2)
            
            # Проверяем, что файл был создан
            self.assertTrue(os.path.exists(temp_file_path))
            
        finally:
            # Удаляем временный файл
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    @patch('yandex_disk_client.YandexDiskClient._make_request')
    @patch('yandex_disk_client.YandexDiskClient._upload_file_with_retry')
    def test_upload_success(self, mock_upload_retry, mock_make_request):
        """Тест успешной загрузки файла"""
        # Создаем временный файл для загрузки
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"upload content")
            temp_file_path = temp_file.name
        
        try:
            # Мок для получения ссылки на загрузку
            mock_response1 = Mock()
            mock_response1.status_code = 200
            mock_response1.json.return_value = {"href": "http://upload.url"}
            
            # Мок для самой загрузки
            mock_response2 = Mock()
            mock_response2.status_code = 201
            mock_upload_retry.return_value = mock_response2
            
            mock_make_request.return_value = mock_response1
            
            # Выполняем загрузку
            result = self.client.upload(Path(temp_file_path), Path("/test.txt"))
            
            # Проверяем результат
            self.assertTrue(result)
            mock_make_request.assert_called_once()
            mock_upload_retry.assert_called_once()
            
        finally:
            # Удаляем временный файл
            os.unlink(temp_file_path)


if __name__ == '__main__':
    unittest.main() 