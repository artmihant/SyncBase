import unittest
from src.main import hello_world
from src.calculator import Calculator

class TestIntegration(unittest.TestCase):
    
    def test_main_workflow(self):
        """Тест основного workflow"""
        result = hello_world()
        self.assertIn("Hello", result)
        
        calc_result = Calculator.add(5, 3)
        self.assertEqual(calc_result, 8)
