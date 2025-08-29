from stellar_sdk import Server, Keypair
from stellar_sdk.exceptions import NotFoundError
from . import config
import logging
import aiohttp
import json

# Настраиваем логирование
logger = logging.getLogger(__name__)

class StellarClient:
    def __init__(self):
        if config.STELLAR_NETWORK == 'testnet':
            self.server = Server('https://horizon-testnet.stellar.org')
        else:
            self.server = Server('https://horizon.stellar.org')
        
        # Parse MTLAP asset
        asset_parts = config.MTLAP_ASSET.split(':')
        self.mtlap_code = asset_parts[0]
        self.mtlap_issuer = asset_parts[1]
        
        # Логируем настройки MTLAP для отладки
        logger.info(f"MTLAP Asset: {config.MTLAP_ASSET}")
        logger.info(f"MTLAP Code: {self.mtlap_code}")
        logger.info(f"MTLAP Issuer: {self.mtlap_issuer}")
    
    async def check_account_exists(self, address: str) -> bool:
        """Проверяет существование аккаунта"""
        try:
            account = self.server.load_account(address)
            return True
        except NotFoundError:
            return False
    
    async def check_trustline(self, address: str) -> bool:
        """Проверяет наличие линии доверия к MTLAP токену"""
        try:
            account = self.server.load_account(address)
            
            # Безопасно получаем балансы
            balances = getattr(account, 'balances', [])
            if not balances:
                # Если балансы недоступны, пробуем альтернативный способ
                try:
                    balances = account.balances
                except AttributeError:
                    # Пробуем получить балансы из raw_data
                    try:
                        if hasattr(account, 'raw_data') and 'balances' in account.raw_data:
                            balances = account.raw_data['balances']
                        else:
                            balances = []
                    except Exception:
                        balances = []
            
            # Проверяем балансы на наличие MTLAP
            for balance in balances:
                # Проверяем, является ли balance словарем или объектом
                if isinstance(balance, dict):
                    asset_type = balance.get('asset_type')
                    asset_code = balance.get('asset_code')
                    asset_issuer = balance.get('asset_issuer')
                else:
                    # Если это объект, используем атрибуты
                    asset_type = getattr(balance, 'asset_type', None)
                    asset_code = getattr(balance, 'asset_code', None)
                    asset_issuer = getattr(balance, 'asset_issuer', None)
                
                if (asset_type == 'credit_alphanum12' and 
                    asset_code == self.mtlap_code and 
                    asset_issuer == self.mtlap_issuer):
                    return True
            
            return False
        except NotFoundError:
            return False
        except Exception as e:
            # Логируем любые другие ошибки
            logger.error(f"Error in check_trustline for {address}: {e}")
            return False
    
    async def check_recommendation(self, address: str) -> dict:
        """Проверяет наличие рекомендации от верифицированного участника МТЛА"""
        try:
            # Скачиваем данные с BSN Expert
            logger.info(f"Fetching BSN data from https://bsn.expert/json")
            
            # Создаем сессию с правильным SSL контекстом для HTTPS
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get('https://bsn.expert/json') as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch BSN data: {response.status}")
                        return {
                            'has_recommendation': False,
                            'error': f'Failed to fetch BSN data: {response.status}'
                        }
                    
                    bsn_data = await response.json()
                    logger.info(f"✓ BSN data fetched successfully ({len(bsn_data.get('accounts', {}))} accounts)")
            
            # Получаем аккаунты для обработки
            accounts = bsn_data.get('accounts', {})
            
            # Ищем рекомендации для указанного адреса
            recommendations = []
            verified_recommendations = []
            
            # Собираем все уникальные теги (без логирования каждого)
            all_tags = set()
            for account_id, account_data in accounts.items():
                if 'tags' in account_data:
                    all_tags.update(account_data['tags'].keys())
            
            # Тихо проверяем наличие тега RecommendToMTLA
            has_recommend_tag = 'RecommendToMTLA' in all_tags
            if has_recommend_tag:
                logger.info("✓ Found RecommendToMTLA tag in BSN data")
            else:
                logger.warning("✗ RecommendToMTLA tag NOT found in BSN data")
            
            # Проверяем все аккаунты на наличие ссылок RecommendToMTLA
            for account_id, account_data in accounts.items():
                if 'tags' in account_data:
                    for tag_name, tag_values in account_data['tags'].items():
                        if tag_name == 'RecommendToMTLA' and isinstance(tag_values, list):
                            for recommended_address in tag_values:
                                if recommended_address == address:
                                    # Проверяем баланс MTLAP у рекомендателя
                                    mtlap_balance = 0
                                    balances = account_data.get('balances', {})
                                    if 'MTLAP' in balances:
                                        try:
                                            mtlap_balance = float(balances['MTLAP'])
                                        except (ValueError, TypeError):
                                            mtlap_balance = 0
                                    
                                    recommendation_info = {
                                        'recommender': account_id,
                                        'mtlap_balance': mtlap_balance,
                                        'is_verified': mtlap_balance >= 2.0
                                    }
                                    
                                    recommendations.append(recommendation_info)
                                    
                                    if recommendation_info['is_verified']:
                                        verified_recommendations.append(recommendation_info)
                                    
                                    logger.info(f"✓ Found recommendation from {account_id} with {mtlap_balance} MTLAP")
            
            # Определяем результат
            has_verified_recommendation = len(verified_recommendations) > 0
            has_any_recommendation = len(recommendations) > 0
            
            result = {
                'has_recommendation': has_verified_recommendation,
                'has_any_recommendation': has_any_recommendation,
                'total_recommendations': len(recommendations),
                'verified_recommendations': len(verified_recommendations),
                'recommendations': recommendations,
                'verified_recommendations_list': verified_recommendations
            }
            
            logger.info(f"Recommendation check result for {address}: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error in check_recommendation for {address}: {e}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Error details: {str(e)}")
            
            return {
                'has_recommendation': False,
                'has_any_recommendation': False,
                'error': str(e)
            }
    
    async def get_account_info(self, address: str) -> dict:
        """Получает информацию об аккаунте"""
        try:
            account = self.server.load_account(address)
            
            # Получаем информацию об объекте account (без лишнего логирования)
            
            # Проверяем линию доверия и баланс MTLAP
            mtlap_balance = 0
            has_trustline = False
            
            # Безопасно получаем балансы
            balances = getattr(account, 'balances', [])
            
            if not balances:
                # Если балансы недоступны, пробуем альтернативный способ
                try:
                    balances = account.balances
                except AttributeError:
                    # Пробуем получить балансы из raw_data
                    try:
                        if hasattr(account, 'raw_data') and 'balances' in account.raw_data:
                            balances = account.raw_data['balances']
                        else:
                            balances = []
                    except Exception:
                        balances = []
            
            # Проверяем балансы на наличие MTLAP
            for balance in balances:
                # Проверяем, является ли balance словарем или объектом
                if isinstance(balance, dict):
                    asset_type = balance.get('asset_type')
                    asset_code = balance.get('asset_code')
                    asset_issuer = balance.get('asset_issuer')
                    balance_value = balance.get('balance', '0')
                else:
                    # Если это объект, используем атрибуты
                    asset_type = getattr(balance, 'asset_type', None)
                    asset_code = getattr(balance, 'asset_code', None)
                    asset_issuer = getattr(balance, 'asset_issuer', None)
                    balance_value = getattr(balance, 'balance', '0')
                
                if (asset_type == 'credit_alphanum12' and 
                    asset_code == self.mtlap_code and 
                    asset_issuer == self.mtlap_issuer):
                    has_trustline = True
                    mtlap_balance = float(balance_value)
                    logger.info(f"✓ Found MTLAP trustline with balance: {mtlap_balance}")
                    break
            
            # Теперь проверяем рекомендации
            logger.info(f"Starting recommendation check for {address}")
            recommendation_info = await self.check_recommendation(address)
            
            return {
                'exists': True,
                'has_trustline': has_trustline,
                'mtlap_balance': mtlap_balance,
                'balances': balances,
                'recommendation': recommendation_info
            }
        except NotFoundError:
            return {
                'exists': False,
                'has_trustline': False,
                'mtlap_balance': 0,
                'balances': [],
                'recommendation': {'has_recommendation': False, 'has_any_recommendation': False}
            }
        except Exception as e:
            # Логируем любые другие ошибки
            logger.error(f"Error in get_account_info for {address}: {e}")
            return {
                'exists': False,
                'has_trustline': False,
                'mtlap_balance': 0,
                'balances': [],
                'recommendation': {'has_recommendation': False, 'has_any_recommendation': False},
                'error': str(e)
            }
