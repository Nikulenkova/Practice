import psycopg2
import requests
import time
from typing import Dict, List, Optional, Tuple
import config

DB_CONFIG = config.DB_CONFIG

PROFESSIONAL_ROLES = ['156', '160', '10', '12', '150', '25', '165', '36', '73',
    '155', '96', '164', '104', '157', '107', '112', '113', '148',
    '114', '116', '121', '124', '125', '126']

SEARCH_PARAMS = {
    'professional_role': PROFESSIONAL_ROLES,
    'area': 72,
    'experience': 'noExperience',
    'employment': 'probation',
    'per_page': 100,
    'page': 0,
    'order_by': 'publication_time'
}

class VacancyDatabase:

    def __init__(self, config: Dict):
        self.config = config
        self.connection = None
        self.cursor = None

    def connect(self) -> bool:
        try:
            self.connection = psycopg2.connect(**self.config)
            self.cursor = self.connection.cursor()

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS employer (
                    id VARCHAR(50) PRIMARY KEY,
                    name VARCHAR(200),
                    description TEXT,
                    site_url VARCHAR(500),
                    area_name VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS vacancy (
                    id SERIAL PRIMARY KEY,
                    hh_id VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(300) NOT NULL,
                    description TEXT,
                    employer_id VARCHAR(50),
                    area_name VARCHAR(100),
                    salary_from INTEGER,
                    salary_to INTEGER,
                    published_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employer_id) REFERENCES employer(id) ON DELETE SET NULL
                );
            """)

            self.connection.commit()
            return True

        except psycopg2.OperationalError as e:
            print(f"Ошибка подключения к БД: {e}")
            return False
        except Exception as e:
            print(f"Неожиданная ошибка: {e}")
            return False

    def vacancy_exists(self, hh_id: str) -> bool:
        try:
            self.cursor.execute("SELECT id FROM vacancy WHERE hh_id = %s", (hh_id,))
            return self.cursor.fetchone() is not None
        except Exception as e:
            print(f"Ошибка при проверке существования вакансии: {e}")
            return False

    def save_vacancy(self, vacancy_data: Dict) -> bool:
        try:
            if self.vacancy_exists(vacancy_data['hh_id']):
                update_sql = """
                UPDATE vacancy set 
                name = %s,
                description = %s,
                employer_id = %s,
                area_name = %s,
                salary_from = %s,
                salary_to = %s,
                published_at = %s,
                is_active = %s,
                updated_at = CURRENT_TIMESTAMP
                WHERE hh_id = %s
            """
                update_params = (
                    vacancy_data.get('name', ''),
                    vacancy_data.get('description', ''),
                    vacancy_data.get('employer_id'),
                    vacancy_data.get('area_name', 'Пермь'),
                    vacancy_data.get('salary_from'),
                    vacancy_data.get('salary_to'),
                    vacancy_data.get('published_at'),
                    vacancy_data.get('is_active', True),
                    vacancy_data['hh_id']
                )
                self.cursor.execute(update_sql, update_params)
                self.connection.commit()
                return True

            else:
                sql = """
            INSERT INTO vacancy (
                hh_id, name, description,
                employer_id, area_name, salary_from,
                salary_to, published_at, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

                params = (
                    vacancy_data['hh_id'],
                    vacancy_data.get('name', ''),
                    vacancy_data.get('description', ''),
                    vacancy_data.get('employer_id'),
                    vacancy_data.get('area_name', 'Пермь'),
                    vacancy_data.get('salary_from'),
                    vacancy_data.get('salary_to'),
                    vacancy_data.get('published_at'),
                    vacancy_data.get('is_active', True)
            )

                self.cursor.execute(sql, params)
                self.connection.commit()
                return True

        except Exception as e:
            print(f"Ошибка: {e}")
            self.connection.rollback()
            return False

    def employer_exists(self, employer_id: str) -> bool:
        try:
            self.cursor.execute("SELECT id FROM employer WHERE id = %s", (employer_id,))
            return self.cursor.fetchone() is not None
        except Exception as e:
            print(f"Ошибка при проверке существования работодателя: {e}")
            return False

    def save_employer(self, employer_data: Dict) -> bool:
        try:
            employer_id = employer_data.get('id')
            if not employer_id:
                return False

            name = employer_data.get('name', '')
            description = employer_data.get('description', '')
            site_url = employer_data.get('site_url', '')
            area_name = employer_data.get('area_name', '')

            if self.employer_exists(employer_id):
                update_sql = """
                    UPDATE employer SET
                        name = %s,
                        description = %s,
                        site_url = %s,
                        area_name = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """
                self.cursor.execute(update_sql, (name, description, site_url, area_name, employer_id))

            else:
                sql = """
                    INSERT INTO employer (id, name, description, site_url, area_name)
                    VALUES (%s, %s, %s, %s, %s)
                """
                self.cursor.execute(sql, (employer_id, name, description, site_url, area_name))

            self.connection.commit()
            return True

        except Exception as e:
            print(f"Ошибка сохранения работодателя: {e}")
            self.connection.rollback()
            return False

    def deactivate_vacancies(self, active_hh_ids: set):
        if not active_hh_ids:
            return 0

        self.cursor.execute("""
                UPDATE vacancy 
                SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE is_active = TRUE AND hh_id NOT IN %s""", (tuple(active_hh_ids),))
        self.connection.commit()

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()

class HHruParser:

    VACANCY_URL = "https://api.hh.ru/vacancies"
    EMPLOYER_URL = "https://api.hh.ru/employers"

    def __init__(self):
        self.session = requests.Session()
        ACCESS_TOKEN = config.HH_ACCESS_TOKEN
        USER_AGENT = config.USER_AGENT

        headers = {
            'User-Agent': USER_AGENT,
            'Authorization': f'Bearer {ACCESS_TOKEN}'
        }
        self.session.headers.update(headers)

    def parse_salary(self, salary_data: Optional[Dict]) -> Tuple[Optional[int], Optional[int]]:
        if not salary_data:
            return None, None
        return salary_data.get('from'), salary_data.get('to')

    def fetch_vacancies(self, params: Dict) -> Tuple[List[Dict], set]:
        all_vacancies = []
        fresh_hh_ids = set()
        page = 0

        while True:
            params['page'] = page

            try:
                response = self.session.get(self.VACANCY_URL, params=params, timeout=15)
                if response.status_code != 200:
                    break

                data = response.json()
                items = data.get('items', [])

                if not items:
                    break

                for item in items:
                    try:
                        vacancy = self.process_vacancy_item(item)
                        fresh_hh_ids.add(str(item['id']))
                        if vacancy:
                            all_vacancies.append(vacancy)
                    except Exception as e:
                        print(f"Ошибка обработки вакансии: {e}")
                        continue

                pages = data.get('pages', 0)
                if page >= pages - 1 or page >= 19:
                    break

                time.sleep(1)
                page += 1

            except requests.exceptions.RequestException as e:
                print(f"Ошибка сети: {e}")
                break
            except Exception as e:
                print(f"Неожиданная ошибка: {e}")
                break
        return all_vacancies, fresh_hh_ids

    def process_vacancy_item(self, item: Dict) -> Optional[Dict]:
        try:
            title = item.get('name', '')
            employer = item.get('employer', {})
            employer_id = employer.get('id')

            vacancy_id = item['id']
            vacancy_details = self.fetch_vacancy_details(vacancy_id)

            if not vacancy_details:
                return None

            salary_from, salary_to = self.parse_salary(vacancy_details.get('salary'))
            published_at = vacancy_details.get('published_at')
            description = vacancy_details.get('description', '')
            is_active = not vacancy_details.get('archived', False)

            vacancy_data = {
                'hh_id': str(vacancy_id),
                'name': title,
                'description': description,
                'employer_id': employer_id,
                'area_name': vacancy_details.get('area', {}).get('name', 'Пермь'),
                'salary_from': salary_from,
                'salary_to': salary_to,
                'published_at': published_at,
                'is_active': is_active
            }

            return vacancy_data

        except Exception as e:
            print(f"Ошибка обработки элемента: {e}")
            return None

    def fetch_vacancy_details(self, vacancy_id: str) -> Optional[Dict]:
        try:
            url = f"{self.VACANCY_URL}/{vacancy_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return None

            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Ошибка сети при запросе вакансии: {e}")
            return None
        except Exception as e:
            print(f"Ошибка при обработке данных вакансии: {e}")
            return None

    def fetch_employer_details(self, employer_id: str) -> Optional[Dict]:
        try:
            url = f"{self.EMPLOYER_URL}/{employer_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return None

            employer_data = response.json()
            return employer_data

        except requests.exceptions.RequestException as e:
            print(f"Ошибка сети при запросе работодателя: {e}")
            return None
        except Exception as e:
            print(f"Ошибка при обработке данных работодателя: {e}")
            return None

    def process_employer_item(self, employer_id: str) -> Optional[Dict]:
        try:
            employer_details = self.fetch_employer_details(employer_id)

            if not employer_details:
                return None

            employer_data = {
                'id': employer_id,
                'name': employer_details.get('name', 'Не указано'),
                'description': employer_details.get('description', ''),
                'site_url': employer_details.get('site_url', ''),
                'area_name': employer_details.get('area', {}).get('name', '')
            }

            return employer_data

        except Exception as e:
            print(f"Ошибка обработки работодателя {employer_id}: {e}")
            return None

def main():

    db = VacancyDatabase(DB_CONFIG)
    if not db.connect():
        return

    parser = HHruParser()
    vacancies, fresh_hh_ids = parser.fetch_vacancies(SEARCH_PARAMS)

    if not vacancies:
        db.close()
        return

    unique_employers = {}

    for vacancy in vacancies:
        employer_id = vacancy.get('employer_id')
        if employer_id and employer_id not in unique_employers:
            employer_data = parser.process_employer_item(employer_id)
            if employer_data:
                unique_employers[employer_id] = employer_data

    for employer_data in unique_employers.values():
        db.save_employer(employer_data)

    for vacancy in vacancies:
        db.save_vacancy(vacancy)

    db.deactivate_vacancies(fresh_hh_ids)
    db.close()

    url1 = config.URL_1
    url2 = config.URL_2
    try:
        response1 = requests.get(url1, timeout=30)
        response2 = requests.get(url2, timeout=30)

        if response1.status_code != 200:
            print(f"ETL {url1} не выполнен: статус {response1.status_code}")

        if response2.status_code != 200:
            print(f"ETL {url2} не выполнен: статус {response2.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе: {e}")

if __name__ == "__main__":
    main()
