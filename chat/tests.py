from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ads.models import Ad, Category

from . import services
from .models import Conversation, Message

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class ChatTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user('seller', password='pass12345')
        cls.buyer = User.objects.create_user('buyer', password='pass12345')
        cls.other = User.objects.create_user('other', password='pass12345')
        cat = Category.objects.create(name='Хобби', slug='hobby')
        cls.ad = Ad.objects.create(
            author=cls.seller, category=cat, title='Гитара', description='x',
            price=Decimal('9000'), city='Казань',
        )

    def start(self, text='Здравствуйте! Ещё продаёте?'):
        return services.start_conversation(self.ad, self.buyer, text)


class StartConversationTests(ChatTestCase):
    def test_button_on_ad_page(self):
        self.client.force_login(self.buyer)
        response = self.client.get(self.ad.get_absolute_url())
        self.assertContains(response, reverse('chat:start', args=[self.ad.pk]))

    def test_anonymous_redirected_to_login(self):
        url = reverse('chat:start', args=[self.ad.pk])
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_start_page_creates_nothing_until_first_message(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('chat:start', args=[self.ad.pk]))
        self.assertContains(response, 'Напишите продавцу первым')
        self.assertFalse(Conversation.objects.exists())

    def test_first_message_creates_conversation(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse('chat:start', args=[self.ad.pk]), {'text': ' Привет '})
        conv = Conversation.objects.get()
        self.assertRedirects(response, f'{conv.get_absolute_url()}#chat-form')
        self.assertEqual((conv.buyer, conv.seller, conv.ad_title), (self.buyer, self.seller, 'Гитара'))
        self.assertEqual(conv.messages.get().text, 'Привет')

    def test_second_start_reuses_conversation(self):
        conv = self.start()
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('chat:start', args=[self.ad.pk]))
        self.assertRedirects(response, conv.get_absolute_url())
        self.client.post(reverse('chat:start', args=[self.ad.pk]), {'text': 'Ещё раз'})
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(conv.messages.count(), 2)

    def test_author_cannot_write_to_himself(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse('chat:start', args=[self.ad.pk]), {'text': 'x'})
        self.assertRedirects(response, self.ad.get_absolute_url())
        self.assertFalse(Conversation.objects.exists())

    def test_cannot_start_on_inactive_ad(self):
        Ad.objects.filter(pk=self.ad.pk).update(is_active=False)
        self.client.force_login(self.buyer)
        self.client.post(reverse('chat:start', args=[self.ad.pk]), {'text': 'x'})
        self.assertFalse(Conversation.objects.exists())

    def test_empty_message_rejected(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse('chat:start', args=[self.ad.pk]), {'text': '   '})
        self.assertContains(response, 'Сообщение пустое.')
        self.assertFalse(Conversation.objects.exists())


class ConversationTests(ChatTestCase):
    def test_seller_reply_and_read_status(self):
        conv = self.start()
        self.assertEqual(services.unread_messages(self.seller).count(), 1)

        self.client.force_login(self.seller)
        response = self.client.get(conv.get_absolute_url())
        self.assertContains(response, 'Ещё продаёте?')
        self.assertEqual(services.unread_messages(self.seller).count(), 0)

        self.client.post(conv.get_absolute_url(), {'text': 'Да, продаю'})
        self.assertEqual(services.unread_messages(self.buyer).count(), 1)
        self.assertEqual(conv.messages.last().sender, self.seller)

    def test_outsider_gets_404(self):
        conv = self.start()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(conv.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(conv.get_absolute_url(), {'text': 'x'}).status_code, 404)
        updates = reverse('chat:updates', args=[conv.pk])
        self.assertEqual(self.client.get(updates).status_code, 404)

    def test_message_is_escaped(self):
        conv = self.start('<script>alert(1)</script>')
        self.client.force_login(self.seller)
        response = self.client.get(conv.get_absolute_url())
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_ajax_send_returns_new_messages(self):
        conv = self.start()
        first = conv.messages.get()
        self.client.force_login(self.seller)
        response = self.client.post(
            conv.get_absolute_url(), {'text': 'Да', 'after': first.pk}, **AJAX,
        )
        data = response.json()
        self.assertIn('Да', data['html'])
        self.assertNotIn('Ещё продаёте', data['html'])
        self.assertEqual(data['last_id'], conv.messages.last().pk)

    def test_ajax_empty_message_error(self):
        conv = self.start()
        self.client.force_login(self.buyer)
        response = self.client.post(conv.get_absolute_url(), {'text': ''}, **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Сообщение пустое.')

    def test_updates_marks_read_and_reports_read_upto(self):
        conv = self.start()
        msg = conv.messages.get()
        url = reverse('chat:updates', args=[conv.pk])

        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(url, {'after': 0}).json()['read_upto'], 0)

        self.client.force_login(self.seller)
        data = self.client.get(url, {'after': 0}).json()
        self.assertIn('Ещё продаёте', data['html'])
        self.assertEqual(data['unread_total'], 0)
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)

        self.client.force_login(self.buyer)
        data = self.client.get(url, {'after': msg.pk}).json()
        self.assertEqual(data['html'].strip(), '')
        self.assertEqual(data['read_upto'], msg.pk)

    def test_conversation_survives_ad_deletion(self):
        conv = self.start()
        self.ad.delete()
        conv.refresh_from_db()
        self.assertIsNone(conv.ad)
        self.client.force_login(self.seller)
        response = self.client.get(conv.get_absolute_url())
        self.assertContains(response, 'Объявление удалено')
        self.client.post(conv.get_absolute_url(), {'text': 'Уже продал'})
        self.assertEqual(conv.messages.count(), 2)


class InboxTests(ChatTestCase):
    def test_inbox_lists_conversations_with_unread(self):
        conv = self.start()
        services.send_message(conv, self.buyer, 'Можно сегодня?')
        self.client.force_login(self.seller)
        response = self.client.get(reverse('chat:inbox'))
        self.assertContains(response, 'Можно сегодня?')
        self.assertContains(response, 'buyer')
        self.assertEqual(response.context['conversations'][0].unread, 2)
        self.assertEqual(response.context['header_unread'], 2)

    def test_inbox_empty_for_outsider(self):
        self.start()
        self.client.force_login(self.other)
        response = self.client.get(reverse('chat:inbox'))
        self.assertContains(response, 'Здесь будут ваши переписки')

    def test_filter_by_own_ad(self):
        self.start()
        self.client.force_login(self.seller)
        response = self.client.get(reverse('chat:inbox'), {'ad': self.ad.pk})
        self.assertEqual(len(response.context['conversations']), 1)
        self.assertEqual(response.context['filter_ad'], self.ad)

    def test_author_sees_messages_link_on_ad(self):
        self.start()
        self.client.force_login(self.seller)
        response = self.client.get(self.ad.get_absolute_url())
        self.assertContains(response, 'Сообщения по объявлению (1)')

    def test_buyer_sees_link_to_existing_conversation(self):
        conv = self.start()
        self.client.force_login(self.buyer)
        response = self.client.get(self.ad.get_absolute_url())
        self.assertContains(response, conv.get_absolute_url())
        self.assertContains(response, 'Перейти к переписке')

    def test_conversations_sorted_by_last_message(self):
        ad2 = Ad.objects.create(
            author=self.other, category=self.ad.category, title='Барабан', description='x',
            price=Decimal('100'), city='Казань',
        )
        first = self.start()
        second = services.start_conversation(ad2, self.buyer, 'Привет')
        services.send_message(first, self.seller, 'Свежий ответ')
        self.assertEqual(list(Conversation.for_user(self.buyer)), [first, second])
        self.assertEqual(Message.objects.count(), 3)
