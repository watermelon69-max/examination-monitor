from pathlib import Path
import yaml


class Config:
    def __init__(self, config_path=None):
        self.config_path = Path(config_path or Path(__file__).resolve().parents[3] / 'config/settings.yaml')
        with self.config_path.open(encoding='utf-8') as handle:
            self.config = yaml.safe_load(handle) or {}

    def get(self, key_path, default=None):
        value = self.config
        for key in key_path.split('.'):
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value

    @property
    def project_root(self):
        return self.config_path.parent.parent


config = Config()
