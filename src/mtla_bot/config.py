import os
from dotenv import load_dotenv

# Загружаем .env файл если он существует
load_dotenv()

def get_secret(key, default=None):
    """
    Получает секрет из Docker secrets или переменных окружения.
    Приоритет: Docker secrets > .env файл > значение по умолчанию
    
    Args:
        key (str): Ключ секрета
        default: Значение по умолчанию
    
    Returns:
        str: Значение секрета или None
    """
    # Сначала пробуем Docker secrets
    secret_path = f"/run/secrets/{key}"
    if os.path.exists(secret_path):
        try:
            with open(secret_path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            print(f"Warning: Failed to read Docker secret {key}: {e}")
    
    # Если секрет не найден, используем переменную окружения
    return os.getenv(key, default)

# Telegram Bot Token
TELEGRAM_TOKEN = get_secret('TELEGRAM_TOKEN')

# MongoDB settings (используем значения по умолчанию)
MONGODB_URI = get_secret('MONGODB_URI', 'mongodb://localhost:27017/')
MONGODB_DB = get_secret('MONGODB_DB', 'mtla_join_bot')
MONGODB_COLLECTION = get_secret('MONGODB_COLLECTION', 'users')

# Stellar Network (используем mainnet по умолчанию)
STELLAR_NETWORK = get_secret('STELLAR_NETWORK', 'public')

# MTLAP Token Asset (используем актуальный по умолчанию)
MTLAP_ASSET = get_secret('MTLAP_ASSET', 'MTLAP:GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA')

# Admin IDs
ADMIN_IDS = []
admin_ids_str = get_secret('ADMIN_IDS', '')
if admin_ids_str:
    try:
        ADMIN_IDS = [int(admin_id.strip()) for admin_id in admin_ids_str.split(',') if admin_id.strip()]
    except ValueError as e:
        print(f"Warning: Invalid ADMIN_IDS format: {e}")
        ADMIN_IDS = []

# Links
LINKS = {
    'ru': {
        'username_guide': 'https://core.stellar.org/docs/glossary/accounts/#username',
        'agreement_link': get_secret('AGREEMENT_LINK_RU', 'https://github.com/Montelibero/MTLA-Documents/blob/main/Internal/Agreement/Agreement.ru.md'),
        'mmvb_link': 'https://t.me/MyMTLWalletBot',
        'light_entry_article': 'https://montelibero.org/2022/03/10/quick-entry-to-the-montelibero-tokenomics/',
        'mtlap_trustline': 'https://eurmtl.me/asset/MTLAP',
        'square_chat': 'https://t.me/Montelibero_Agora',
        'feedback_bot': '@mtl_helper_bot'
    },
    'en': {
        'username_guide': 'https://core.stellar.org/docs/glossary/accounts/#username',
        'agreement_link': get_secret('AGREEMENT_LINK_EN', 'https://github.com/Montelibero/MTLA-Documents/blob/main/Internal/Agreement/Agreement.en.md'),
        'mmvb_link': 'https://t.me/MyMTLWalletBot',
        'light_entry_article': 'https://montelibero.org/2022/03/10/quick-entry-to-the-montelibero-tokenomics/',
        'mtlap_trustline': 'https://eurmtl.me/asset/MTLAP',
        'square_chat': 'https://t.me/Montelibero_Agora',
        'feedback_bot': '@mtl_helper_bot'
    }
}
