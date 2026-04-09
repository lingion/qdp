from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Mapping, Optional, Tuple

CONFIG_FILE = os.path.join(os.path.expanduser('~'), '.config', 'qobuz-dl', 'config.ini')

ACCOUNTS_SECTION_PREFIX = 'account:'
ACTIVE_ACCOUNT_KEY = 'active_account'
ACCOUNT_FIELDS = [
    'use_token', 'email', 'password', 'user_id', 'user_auth_token', 'app_id', 'secrets',
]
ACCOUNT_META_FIELDS = [
    'account_name', 'account_type', 'region', 'expiry_date', 'label', 'last_used',
    'email_masked', 'user_id_masked', 'status', 'status_detail', 'remark',
]


@dataclass(frozen=True)
class AccountConfig:
    app_id: str = ''
    user_auth_token: str = ''
    use_token: bool = False
    email: str = ''
    password: str = ''
    user_id: str = ''
    secrets: Tuple[str, ...] = ()
    user_agent: str = ''
    source: str = 'unknown'

    def as_dict(self) -> Dict[str, str]:
        payload = {
            'app_id': self.app_id,
            'user_auth_token': self.user_auth_token,
            'use_token': 'true' if self.use_token else 'false',
            'email': self.email,
            'password': self.password,
            'user_id': self.user_id,
            'secrets': ','.join(self.secrets),
            'user_agent': self.user_agent,
            'source': self.source,
        }
        return payload


class AccountConfigError(ValueError):
    def __init__(self, errors: List[str], config: Optional[AccountConfig] = None):
        self.errors = list(errors)
        self.config = config
        super().__init__('; '.join(self.errors))


SUPPORTED_ACCOUNT_ENV = {
    'app_id': ('QDP_APP_ID', 'QOBUZ_APP_ID'),
    'user_auth_token': ('QDP_AUTH_TOKEN', 'QOBUZ_AUTH_TOKEN', 'QOBUZ_USER_AUTH_TOKEN'),
    'email': ('QDP_EMAIL', 'QOBUZ_EMAIL'),
    'password': ('QDP_PASSWORD', 'QOBUZ_PASSWORD'),
    'user_id': ('QDP_USER_ID', 'QOBUZ_USER_ID'),
    'secrets': ('QDP_SECRETS', 'QOBUZ_SECRETS'),
    'user_agent': ('QDP_USER_AGENT', 'QOBUZ_USER_AGENT'),
    'use_token': ('QDP_USE_TOKEN', 'QOBUZ_USE_TOKEN'),
}


def _load_config(config_file: str = CONFIG_FILE) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(config_file)
    return config


def _save_config(config: configparser.ConfigParser, config_file: str = CONFIG_FILE):
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, 'w') as fp:
        config.write(fp)


def _sanitize_account_name(name: str) -> str:
    name = (name or '').strip()
    name = re.sub(r'\s+', '-', name)
    name = re.sub(r'[^a-zA-Z0-9_.-]', '', name)
    return name[:64]


def _mask_email(email: str) -> str:
    email = (email or '').strip()
    if not email or '@' not in email:
        return email or ''
    local, domain = email.split('@', 1)
    left = local[:3]
    right = local[-2:] if len(local) > 2 else ''
    return f"{left}..{right}@{domain}"


def _mask_user_id(user_id: str) -> str:
    user_id = str(user_id or '').strip()
    return user_id[:4] if len(user_id) > 4 else user_id


def _normalize_expiry(raw: str) -> str:
    raw = str(raw or '').strip()
    if not raw:
        return ''
    try:
        if 'T' in raw:
            raw = raw.split('T', 1)[0]
        d = date.fromisoformat(raw)
        return d.isoformat()
    except Exception:
        return raw


def _stringify_bool(value: object) -> str:
    return 'true' if _bool_from_value(value) else 'false'


def _bool_from_value(value: object) -> bool:
    text = str(value or '').strip().lower()
    return text in {'1', 'true', 'yes', 'on'}


def _first_env(env: Optional[Mapping[str, str]], *names: str) -> str:
    source = env if env is not None else os.environ
    for name in names:
        value = source.get(name)
        if value is not None and str(value).strip() != '':
            return str(value).strip()
    return ''


def _split_secrets(raw: object) -> Tuple[str, ...]:
    return tuple([part.strip() for part in str(raw or '').split(',') if part.strip()])


def _read_defaults_from_config(config_file: str = CONFIG_FILE) -> Dict[str, str]:
    config = _load_config(config_file)
    defaults: Dict[str, str] = {}
    if config.has_section('DEFAULT') or 'DEFAULT' in config:
        defaults.update(dict(config['DEFAULT']))
    active_name = defaults.get(ACTIVE_ACCOUNT_KEY, '').strip()
    if active_name:
        section = ACCOUNTS_SECTION_PREFIX + active_name
        if config.has_section(section):
            for key, value in dict(config[section]).items():
                defaults.setdefault(key, value)
    return defaults


def _defaults_to_account_config(defaults: Mapping[str, str], source: str) -> AccountConfig:
    return AccountConfig(
        app_id=str(defaults.get('app_id', '') or '').strip(),
        user_auth_token=str(defaults.get('user_auth_token', '') or '').strip(),
        use_token=_bool_from_value(defaults.get('use_token', 'false')),
        email=str(defaults.get('email', '') or '').strip(),
        password=str(defaults.get('password', '') or '').strip(),
        user_id=str(defaults.get('user_id', '') or '').strip(),
        secrets=_split_secrets(defaults.get('secrets', '')),
        user_agent=str(defaults.get('user_agent', '') or '').strip(),
        source=source,
    )


def load_account_config(config_file: str = CONFIG_FILE, env: Optional[Mapping[str, str]] = None) -> AccountConfig:
    defaults = _read_defaults_from_config(config_file)
    source = 'config'

    env_app_id = _first_env(env, *SUPPORTED_ACCOUNT_ENV['app_id'])
    env_user_auth_token = _first_env(env, *SUPPORTED_ACCOUNT_ENV['user_auth_token'])
    env_email = _first_env(env, *SUPPORTED_ACCOUNT_ENV['email'])
    env_password = _first_env(env, *SUPPORTED_ACCOUNT_ENV['password'])
    env_user_id = _first_env(env, *SUPPORTED_ACCOUNT_ENV['user_id'])
    env_secrets = _first_env(env, *SUPPORTED_ACCOUNT_ENV['secrets'])
    env_user_agent = _first_env(env, *SUPPORTED_ACCOUNT_ENV['user_agent'])
    env_use_token = _first_env(env, *SUPPORTED_ACCOUNT_ENV['use_token'])

    if any([env_app_id, env_user_auth_token, env_email, env_password, env_user_id, env_secrets, env_user_agent, env_use_token]):
        source = 'environment'
        if env_app_id:
            defaults['app_id'] = env_app_id
        if env_user_auth_token:
            defaults['user_auth_token'] = env_user_auth_token
        if env_email:
            defaults['email'] = env_email
        if env_password:
            defaults['password'] = env_password
        if env_user_id:
            defaults['user_id'] = env_user_id
        if env_secrets:
            defaults['secrets'] = env_secrets
        if env_user_agent:
            defaults['user_agent'] = env_user_agent
        if env_use_token:
            defaults['use_token'] = _stringify_bool(env_use_token)
        elif env_user_auth_token:
            defaults['use_token'] = 'true'

    return _defaults_to_account_config(defaults, source=source)


def validate_account_config(config: AccountConfig) -> List[str]:
    errors: List[str] = []
    if not config.app_id:
        errors.append('Missing app_id. Set QOBUZ_APP_ID/QDP_APP_ID or configure app_id in ~/.config/qobuz-dl/config.ini.')

    if config.use_token or config.user_auth_token:
        if not config.user_auth_token:
            errors.append('Missing user_auth_token for token mode. Set QOBUZ_USER_AUTH_TOKEN/QDP_AUTH_TOKEN or configure user_auth_token.')
    else:
        if not config.email:
            errors.append('Missing email for password mode. Set QOBUZ_EMAIL/QDP_EMAIL or configure email.')
        if not config.password:
            errors.append('Missing password for password mode. Set QOBUZ_PASSWORD/QDP_PASSWORD or configure password.')

    return errors


def load_account_config_or_raise(config_file: str = CONFIG_FILE, env: Optional[Mapping[str, str]] = None) -> AccountConfig:
    config = load_account_config(config_file=config_file, env=env)
    errors = validate_account_config(config)
    if errors:
        raise AccountConfigError(errors, config=config)
    return config


def expiry_status(expiry: str) -> tuple[str, str]:
    expiry = _normalize_expiry(expiry)
    if not expiry:
        return ('永久/未知', '')
    try:
        d = date.fromisoformat(expiry)
        today = date.today()
        delta = (d - today).days
        if delta > 0:
            return (f"----{d.year}/{d.month}/{d.day} EXP.", f"还剩 {delta} 天")
        if delta == 0:
            return (f"----{d.year}/{d.month}/{d.day} EXP.", '今天到期')
        return (f"----{d.year}/{d.month}/{d.day} EXP.", f"已过期 {-delta} 天")
    except Exception:
        return (f"----{expiry} EXP.", '')


def format_account_display(index: int, name: str, data: Dict[str, str], active_name: str = '') -> str:
    acc_type = data.get('account_type') or ('token' if data.get('use_token') == 'true' else 'account')
    region = (data.get('region') or '--').upper()
    main = data.get('email_masked') or data.get('email') or data.get('user_id_masked') or data.get('user_id') or name
    expiry_text, remain_text = expiry_status(data.get('expiry_date', ''))
    status = data.get('status', '')
    status_suffix = f" [{status}]" if status else ''
    remain_suffix = f" ({remain_text})" if remain_text else ''
    remark = data.get('remark', '').strip()
    remark_suffix = f"  # {remark}" if remark else ''
    active = '  *ACTIVE*' if active_name and active_name == name else ''
    return f"{index}.({acc_type})[{region}]{main}  {expiry_text}{remain_suffix}{status_suffix}{active}{remark_suffix}"


def list_accounts(config_file: str = CONFIG_FILE) -> List[Tuple[str, Dict[str, str]]]:
    config = _load_config(config_file)
    accounts: List[Tuple[str, Dict[str, str]]] = []
    for section in config.sections():
        if section.startswith(ACCOUNTS_SECTION_PREFIX):
            name = section[len(ACCOUNTS_SECTION_PREFIX):]
            accounts.append((name, dict(config[section])))
    accounts.sort(key=lambda item: item[0].lower())
    return accounts


def get_active_account(config_file: str = CONFIG_FILE) -> str:
    config = _load_config(config_file)
    return config['DEFAULT'].get(ACTIVE_ACCOUNT_KEY, '') if ('DEFAULT' in config or config.has_section('DEFAULT')) else ''


def _account_identity(source: Dict[str, str]) -> tuple[str, str, str]:
    acc_type = 'token' if source.get('use_token') == 'true' else 'account'
    email = (source.get('email') or '').strip().lower()
    uid = (source.get('user_id') or '').strip()
    return (acc_type, email, uid)


def save_current_as_account(name: str, defaults: Dict[str, str] | None = None, config_file: str = CONFIG_FILE, meta: Dict[str, str] | None = None) -> str:
    config = _load_config(config_file)
    safe_name = _sanitize_account_name(name)
    if not safe_name:
        raise ValueError('账号名称不能为空')
    source = defaults or dict(config['DEFAULT'])
    source_identity = _account_identity(source)
    section = ACCOUNTS_SECTION_PREFIX + safe_name

    if config.has_section(section):
        existing_identity = _account_identity(dict(config[section]))
        if existing_identity != source_identity:
            fallback_name = source.get('email') or source.get('user_id') or safe_name
            safe_name = _sanitize_account_name(fallback_name)
            section = ACCOUNTS_SECTION_PREFIX + safe_name

    if not config.has_section(section):
        config.add_section(section)
    for key in ACCOUNT_FIELDS:
        config[section][key] = source.get(key, '')
    payload = dict(meta or {})
    payload.setdefault('account_name', safe_name)
    payload.setdefault('account_type', 'token' if source.get('use_token') == 'true' else 'account')
    payload.setdefault('region', source.get('region', '--'))
    payload.setdefault('expiry_date', _normalize_expiry(source.get('expiry_date', '')))
    payload.setdefault('label', source.get('label', ''))
    payload.setdefault('email_masked', _mask_email(source.get('email', '')))
    payload.setdefault('user_id_masked', _mask_user_id(source.get('user_id', '')))
    payload.setdefault('status', source.get('status', ''))
    payload.setdefault('status_detail', source.get('status_detail', ''))
    payload.setdefault('remark', source.get('remark', ''))
    payload['last_used'] = datetime.now().isoformat(timespec='seconds')
    for key in ACCOUNT_META_FIELDS:
        config[section][key] = payload.get(key, '')
    config['DEFAULT'][ACTIVE_ACCOUNT_KEY] = safe_name
    _save_config(config, config_file)
    return safe_name


def create_account_record(name: str, payload: Dict[str, str], config_file: str = CONFIG_FILE) -> str:
    return save_current_as_account(name, defaults=payload, config_file=config_file, meta=payload)


def switch_account(name: str, config_file: str = CONFIG_FILE) -> str:
    config = _load_config(config_file)
    safe_name = _sanitize_account_name(name)
    section = ACCOUNTS_SECTION_PREFIX + safe_name
    if section not in config:
        raise ValueError(f'账号不存在: {name}')
    for key in ACCOUNT_FIELDS:
        config['DEFAULT'][key] = config[section].get(key, '')
    for key in ('region', 'expiry_date', 'label', 'status', 'status_detail', 'remark'):
        config['DEFAULT'][key] = config[section].get(key, '')
    config['DEFAULT'][ACTIVE_ACCOUNT_KEY] = safe_name
    config[section]['last_used'] = datetime.now().isoformat(timespec='seconds')
    _save_config(config, config_file)
    return safe_name


def update_account_meta(name: str, meta: Dict[str, str], config_file: str = CONFIG_FILE, overwrite_empty: bool = True):
    config = _load_config(config_file)
    safe_name = _sanitize_account_name(name)
    section = ACCOUNTS_SECTION_PREFIX + safe_name
    if section not in config:
        config.add_section(section)
    for key, value in meta.items():
        normalized = str(value or '')
        if not overwrite_empty and not normalized.strip():
            continue
        config[section][key] = normalized
        if key in ('region', 'expiry_date', 'label', 'status', 'status_detail', 'remark') and config['DEFAULT'].get(ACTIVE_ACCOUNT_KEY, '') == safe_name:
            config['DEFAULT'][key] = normalized
    config[section]['last_used'] = datetime.now().isoformat(timespec='seconds')
    _save_config(config, config_file)


def set_account_remark(name: str, remark: str, config_file: str = CONFIG_FILE):
    update_account_meta(name, {'remark': remark}, config_file)


def rename_account(old_name: str, new_name: str, config_file: str = CONFIG_FILE) -> str:
    config = _load_config(config_file)
    old_safe = _sanitize_account_name(old_name)
    new_safe = _sanitize_account_name(new_name)
    old_section = ACCOUNTS_SECTION_PREFIX + old_safe
    new_section = ACCOUNTS_SECTION_PREFIX + new_safe
    if old_section not in config:
        raise ValueError(f'账号不存在: {old_name}')
    if not new_safe:
        raise ValueError('新账号名称不能为空')
    if new_section != old_section and new_section in config:
        raise ValueError(f'账号已存在: {new_name}')
    if new_section != old_section:
        config.add_section(new_section)
        for k, v in config[old_section].items():
            config[new_section][k] = v
        config.remove_section(old_section)
    config[new_section]['account_name'] = new_safe
    if config['DEFAULT'].get(ACTIVE_ACCOUNT_KEY, '') == old_safe:
        config['DEFAULT'][ACTIVE_ACCOUNT_KEY] = new_safe
    _save_config(config, config_file)
    return new_safe


def delete_account(name: str, config_file: str = CONFIG_FILE) -> bool:
    config = _load_config(config_file)
    safe_name = _sanitize_account_name(name)
    section = ACCOUNTS_SECTION_PREFIX + safe_name
    if section not in config:
        return False
    config.remove_section(section)
    if config['DEFAULT'].get(ACTIVE_ACCOUNT_KEY, '') == safe_name:
        config['DEFAULT'][ACTIVE_ACCOUNT_KEY] = ''
    _save_config(config, config_file)
    return True
