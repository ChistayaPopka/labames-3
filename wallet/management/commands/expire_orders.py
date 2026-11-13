from django.core.management.base import BaseCommand

from wallet.services import expire_overdue


class Command(BaseCommand):
    help = 'Закрывает просроченные брони и возвращает покупателям замороженные деньги. Запускать по cron.'

    def handle(self, *args, **options):
        count = expire_overdue()
        self.stdout.write(self.style.SUCCESS(f'Закрыто просроченных броней: {count}'))
