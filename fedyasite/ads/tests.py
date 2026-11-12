from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Ad, Category

User = get_user_model()


class AdTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('owner', password='pass12345')
        cls.other = User.objects.create_user('other', password='pass12345')
        cls.electronics = Category.objects.create(name='Электроника', slug='electronics')
        cls.hobby = Category.objects.create(name='Хобби', slug='hobby')
        cls.laptop = Ad.objects.create(
            author=cls.owner, category=cls.electronics, title='Ноутбук Lenovo',
            description='Рабочий ноутбук', price=45000, city='Москва',
        )
        cls.guitar = Ad.objects.create(
            author=cls.owner, category=cls.hobby, title='Гитара Yamaha',
            description='Акустическая', price=9000, city='Казань',
        )
        cls.hidden = Ad.objects.create(
            author=cls.owner, category=cls.hobby, title='Скрытая палатка',
            description='Снято с публикации', price=100, city='Казань', is_active=False,
        )


class ListViewTests(AdTestCase):
    def titles(self, **params):
        response = self.client.get(reverse('ads:list'), params)
        self.assertEqual(response.status_code, 200)
        return {ad.title for ad in response.context['ads']}

    def test_shows_only_active(self):
        self.assertEqual(self.titles(), {'Ноутбук Lenovo', 'Гитара Yamaha'})

    def test_search_is_case_insensitive_for_cyrillic(self):
        self.assertEqual(self.titles(q='ноутбук'), {'Ноутбук Lenovo'})
        self.assertEqual(self.titles(q='ГИТАРА'), {'Гитара Yamaha'})

    def test_filter_by_category_city_and_price(self):
        self.assertEqual(self.titles(category='hobby'), {'Гитара Yamaha'})
        self.assertEqual(self.titles(city='москва'), {'Ноутбук Lenovo'})
        self.assertEqual(self.titles(price_min=10000), {'Ноутбук Lenovo'})
        self.assertEqual(self.titles(price_max=10000), {'Гитара Yamaha'})

    def test_sort_by_price(self):
        response = self.client.get(reverse('ads:list'), {'sort': 'cheap'})
        self.assertEqual(
            [ad.title for ad in response.context['ads']],
            ['Гитара Yamaha', 'Ноутбук Lenovo'],
        )

    def test_invalid_filter_does_not_break_page(self):
        response = self.client.get(reverse('ads:list'), {'price_min': 'abc'})
        self.assertEqual(response.status_code, 200)


class DetailViewTests(AdTestCase):
    def test_view_counter_ignores_author(self):
        url = self.laptop.get_absolute_url()
        self.client.get(url)
        self.laptop.refresh_from_db()
        self.assertEqual(self.laptop.views, 1)

        self.client.force_login(self.owner)
        self.client.get(url)
        self.laptop.refresh_from_db()
        self.assertEqual(self.laptop.views, 1)

    def test_inactive_ad_visible_only_to_author(self):
        url = self.hidden.get_absolute_url()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)


class EditPermissionTests(AdTestCase):
    def test_create_requires_login(self):
        response = self.client.get(reverse('ads:create'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('ads:create')}")

    def test_create_sets_author(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse('ads:create'), {
            'title': 'Велосипед', 'category': self.hobby.pk, 'condition': 'used',
            'price': '15000', 'city': 'Москва', 'description': 'Горный', 'is_active': 'on',
        })
        ad = Ad.objects.get(title='Велосипед')
        self.assertRedirects(response, ad.get_absolute_url())
        self.assertEqual(ad.author, self.other)

    def test_negative_price_rejected(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse('ads:create'), {
            'title': 'Минус', 'category': self.hobby.pk, 'condition': 'used',
            'price': '-5', 'city': 'Москва', 'description': 'x',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Ad.objects.filter(title='Минус').exists())

    def test_only_author_can_edit_and_delete(self):
        self.client.force_login(self.other)
        for name in ('ads:update', 'ads:delete'):
            url = reverse(name, args=[self.laptop.pk])
            self.assertRedirects(self.client.get(url), reverse('ads:list'))
            self.assertRedirects(self.client.post(url, {'title': 'Взлом'}), reverse('ads:list'))
        self.laptop.refresh_from_db()
        self.assertEqual(self.laptop.title, 'Ноутбук Lenovo')

    def test_author_can_delete(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('ads:delete', args=[self.guitar.pk]))
        self.assertRedirects(response, reverse('ads:my'))
        self.assertFalse(Ad.objects.filter(pk=self.guitar.pk).exists())


class FavoriteTests(AdTestCase):
    def test_toggle(self):
        url = reverse('ads:favorite', args=[self.laptop.pk])
        self.client.force_login(self.other)
        self.client.post(url)
        self.assertIn(self.laptop, self.other.favorite_ads.all())
        response = self.client.get(reverse('ads:favorites'))
        self.assertContains(response, 'Ноутбук Lenovo')
        self.client.post(url)
        self.assertNotIn(self.laptop, self.other.favorite_ads.all())

    def test_get_not_allowed_and_login_required(self):
        url = reverse('ads:favorite', args=[self.laptop.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(self.laptop.favorited_by.exists())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_next_redirect_rejects_external_url(self):
        self.client.force_login(self.other)
        response = self.client.post(
            reverse('ads:favorite', args=[self.laptop.pk]), {'next': 'https://evil.example/'},
        )
        self.assertRedirects(response, self.laptop.get_absolute_url())
