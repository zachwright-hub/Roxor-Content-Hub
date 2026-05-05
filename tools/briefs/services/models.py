import os
import csv
import shutil
from io import StringIO


class ModelLookup:
    MODEL_EXTENSIONS = ['.step', '.stp', '.obj', '.max', '.fbx', '.glb', '.3ds', '.igs', '.dwg']

    def __init__(self, config):
        self.config = config
        self.use_local = config.get('local', {}).get('enabled', True)
        self.model_mapping = None
        self.model_files_index = None
        self.s3_client = None
        if not self.use_local:
            self._init_s3()

    def _init_s3(self):
        import boto3
        s3_config = self.config.get('s3', {})
        if s3_config.get('access_key') and s3_config.get('secret_key'):
            self.s3_client = boto3.client('s3',
                region_name=s3_config.get('region', 'eu-west-2'),
                aws_access_key_id=s3_config['access_key'],
                aws_secret_access_key=s3_config['secret_key']
            )
        else:
            self.s3_client = boto3.client('s3', region_name=s3_config.get('region', 'eu-west-2'))
        self.bucket = s3_config.get('bucket')
        self.models_prefix = s3_config.get('models_prefix', '4-3D/')
        self.mapping_key = s3_config.get('mapping_key', 'FINAL_master_mapping.csv')

    def _load_mapping(self):
        if self.model_mapping is not None:
            return
        if self._load_mapping_db():
            return
        if self.use_local:
            self._load_mapping_local()
        else:
            self._load_mapping_s3()

    def _load_mapping_db(self):
        import sqlite3
        db_path = self.config.get('database')
        if not db_path:
            return False
        try:
            db = sqlite3.connect(db_path)
            db.row_factory = sqlite3.Row
            count = db.execute('SELECT COUNT(*) as c FROM model_mappings').fetchone()['c']
            if count == 0:
                db.close()
                return False
            self.model_mapping = {}
            rows = db.execute('SELECT sku, models FROM model_mappings').fetchall()
            for row in rows:
                if row['sku'] and row['models']:
                    self.model_mapping[row['sku']] = row['models']
            db.close()
            return True
        except Exception as e:
            print(f'DB mapping load failed ({e}), falling back')
            return False

    def _load_mapping_local(self):
        mapping_path = self.config.get('local', {}).get('master_mapping', '')
        if not mapping_path or not os.path.exists(mapping_path):
            self.model_mapping = {}
            return
        self.model_mapping = {}
        with open(mapping_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('sku') and row.get('models'):
                    self.model_mapping[row['sku']] = row['models']

    def _load_mapping_s3(self):
        response = self.s3_client.get_object(Bucket=self.bucket, Key=self.mapping_key)
        content = response['Body'].read().decode('utf-8')
        self.model_mapping = {}
        reader = csv.DictReader(StringIO(content))
        for row in reader:
            if row.get('sku') and row.get('models'):
                self.model_mapping[row['sku']] = row['models']

    def _index_model_files(self):
        if self.model_files_index is not None:
            return
        if self.use_local:
            self._index_model_files_local()
        else:
            self._index_model_files_s3()

    def _index_model_files_local(self):
        self.model_files_index = {}
        models_base = self.config.get('local', {}).get('models_base', '')
        if not models_base or not os.path.exists(models_base):
            return
        for folder_name in os.listdir(models_base):
            if folder_name.startswith('_'):
                continue
            folder_path = os.path.join(models_base, folder_name)
            if os.path.isdir(folder_path):
                self._scan_local_directory(folder_path)

    def _scan_local_directory(self, directory):
        try:
            for entry in os.listdir(directory):
                full_path = os.path.join(directory, entry)
                if os.path.isdir(full_path):
                    self._scan_local_directory(full_path)
                elif os.path.isfile(full_path):
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in self.MODEL_EXTENSIONS:
                        base_name = os.path.splitext(entry)[0]
                        if base_name not in self.model_files_index:
                            self.model_files_index[base_name] = []
                        self.model_files_index[base_name].append(full_path)
        except Exception as e:
            print(f'Error scanning {directory}: {e}')

    def _index_model_files_s3(self):
        self.model_files_index = {}
        paginator = self.s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.models_prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                filename = os.path.basename(key)
                ext = os.path.splitext(filename)[1].lower()
                if ext in self.MODEL_EXTENSIONS:
                    base_name = os.path.splitext(filename)[0]
                    if base_name not in self.model_files_index:
                        self.model_files_index[base_name] = []
                    self.model_files_index[base_name].append(key)

    def get_models_for_sku(self, sku):
        self._load_mapping()
        self._index_model_files()
        if sku not in self.model_mapping:
            return {'found': False, 'models': [], 'files': []}
        model_names = [m.strip() for m in self.model_mapping[sku].replace(';', ',').split(',') if m.strip()]
        files = []
        for model_name in model_names:
            if model_name in self.model_files_index:
                files.extend(self.model_files_index[model_name])
        return {'found': True, 'models': model_names, 'files': files}

    def copy_model_files(self, source_files, destination_folder):
        os.makedirs(destination_folder, exist_ok=True)
        if self.use_local:
            return self._copy_local_files(source_files, destination_folder)
        return self._copy_s3_files(source_files, destination_folder)

    def _copy_local_files(self, source_files, destination_folder):
        copied = []
        for file_path in source_files:
            if os.path.exists(file_path):
                file_name = os.path.basename(file_path)
                dest_path = os.path.join(destination_folder, file_name)
                if not os.path.exists(dest_path):
                    shutil.copy2(file_path, dest_path)
                    copied.append(file_name)
        return copied

    def _copy_s3_files(self, s3_keys, destination_folder):
        copied = []
        for s3_key in s3_keys:
            file_name = os.path.basename(s3_key)
            dest_path = os.path.join(destination_folder, file_name)
            if not os.path.exists(dest_path):
                try:
                    self.s3_client.download_file(self.bucket, s3_key, dest_path)
                    copied.append(file_name)
                except Exception as e:
                    print(f'Error downloading {s3_key}: {e}')
        return copied

    def reload(self):
        self.model_mapping = None
        self.model_files_index = None
        self._load_mapping()
        self._index_model_files()
