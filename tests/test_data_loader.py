import unittest
import os
import tempfile
from eanalizer.data_loader import load_from_enea_csv

class TestDataLoader(unittest.TestCase):
    def test_load_invalid_csv_structure(self):
        """Testuje, czy loader pomija pliki CSV o nieprawidlowej strukturze zamiast rzucac bledem."""
        temp_path = ""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("tariff,zone_name,day_type,start_hour,end_hour,price_per_kwh\nG11,stala,all,0,24,0.97\n")
            temp_path = f.name
        
        try:
            results = load_from_enea_csv(temp_path)
            self.assertEqual(results, [])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_load_valid_enea_csv(self):
        """Testuje wczytywanie prawidlowego pliku (fragmentu)."""
        test_file = "tests/test_data.csv"
        if os.path.exists(test_file):
            results = load_from_enea_csv(test_file)
            self.assertGreater(len(results), 0)

if __name__ == '__main__':
    unittest.main()
