from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from ads.models import Ad, Category

CATEGORIES = [
    ('Электроника', 'electronics'),
    ('Транспорт', 'transport'),
    ('Недвижимость', 'realty'),
    ('Одежда и обувь', 'clothes'),
    ('Дом и сад', 'home'),
    ('Хобби и отдых', 'hobby'),
    ('Услуги', 'services'),
]

ADS = [
    ('electronics', 'Ноутбук Lenovo ThinkPad T14', 45000, 'used', 'Москва',
     'Рабочий ноутбук в хорошем состоянии: 16 ГБ ОЗУ, SSD 512 ГБ. Батарея держит около 6 часов. В комплекте зарядка.'),
    ('electronics', 'Смартфон Samsung Galaxy S23', 38000, 'used', 'Казань',
     'Пользовался год, всегда в чехле и с защитным стеклом. Полный комплект, коробка, чек.'),
    ('electronics', 'Беспроводные наушники Sony', 12500, 'new', 'Москва',
     'Новые, в запечатанной упаковке. Подарили вторые — продаю лишние.'),
    ('transport', 'Велосипед горный Stels Navigator', 15000, 'used', 'Екатеринбург',
     'Рама 19", 21 скорость, дисковые тормоза. Обслужен перед сезоном.'),
    ('transport', 'Зимние шины Nokian R16', 18000, 'used', 'Новосибирск',
     'Комплект из 4 шин 205/55 R16, откатали два сезона, остаток протектора 7 мм.'),
    ('realty', 'Сдам 1-комнатную квартиру у метро', 42000, 'used', 'Москва',
     'Квартира 38 м² в 5 минутах от метро. Мебель и техника есть. Цена за месяц, коммунальные включены.'),
    ('clothes', 'Куртка зимняя мужская, размер L', 5500, 'new', 'Казань',
     'Новая, с бирками — не подошёл размер. Тёплая, до −25 °C.'),
    ('clothes', 'Кроссовки беговые 42 размер', 4200, 'used', 'Санкт-Петербург',
     'Пробег около 100 км, состояние отличное. Продаю из-за смены модели.'),
    ('home', 'Диван угловой раскладной', 22000, 'used', 'Санкт-Петербург',
     'Диван серого цвета, механизм «дельфин», есть ящик для белья. Самовывоз.'),
    ('home', 'Набор садовых инструментов', 3000, 'new', 'Екатеринбург',
     'Лопата, грабли, секатор и тяпка. Новый набор, ни разу не использовался.'),
    ('hobby', 'Акустическая гитара Yamaha F310', 9000, 'used', 'Новосибирск',
     'Отличный инструмент для начинающих. Отдаю вместе с чехлом и тюнером.'),
    ('hobby', 'Палатка туристическая 3-местная', 6500, 'used', 'Казань',
     'Двухслойная, с тамбуром. Использовалась три раза, без повреждений.'),
    ('services', 'Репетитор по математике, ОГЭ и ЕГЭ', 1200, 'new', 'Москва',
     'Подготовка к экзаменам, онлайн и очно. Опыт 8 лет. Цена за занятие 60 минут.'),
    ('services', 'Ремонт компьютеров и ноутбуков', 800, 'new', 'Санкт-Петербург',
     'Диагностика, чистка, замена комплектующих, установка программ. Выезд на дом.'),
]


class Command(BaseCommand):
    help = 'Создаёт категории и демонстрационные объявления.'

    def handle(self, *args, **options):
        categories = {}
        for name, slug in CATEGORIES:
            categories[slug], _ = Category.objects.get_or_create(
                slug=slug, defaults={'name': name},
            )

        User = get_user_model()
        users = []
        for username in ('anna', 'ivan'):
            user, created = User.objects.get_or_create(
                username=username, defaults={'email': f'{username}@example.com'},
            )
            if created:
                user.set_password('demo12345')
                user.save()
            users.append(user)

        created_count = 0
        for i, (slug, title, price, condition, city, description) in enumerate(ADS):
            _, created = Ad.objects.get_or_create(
                title=title,
                defaults={
                    'author': users[i % len(users)],
                    'category': categories[slug],
                    'price': price,
                    'condition': condition,
                    'city': city,
                    'description': description,
                    'phone': '+7 900 000-00-00',
                },
            )
            created_count += created

        self.stdout.write(self.style.SUCCESS(
            f'Готово: категорий — {len(categories)}, новых объявлений — {created_count}. '
            'Демо-пользователи: anna / ivan, пароль demo12345'
        ))
