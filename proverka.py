import telebot
import json
import time
import os
import sqlite3
import threading
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ⚠️ ЗАМЕНИТЕ НА ВАШ ТОКЕН
BOT_TOKEN = "8390334481:AAGM-WTxKe88otShhQYK-YaSlWXKqcLg0fQ"
bot = telebot.TeleBot(BOT_TOKEN)

# Хранилище активных игр
user_games = {}

# ===== СИСТЕМА СИНХРОНИЗАЦИИ =====
class UserManager:
    def init(self):
        self.conn = sqlite3.connect('users_sync.db', check_same_thread=False)
        self.create_table()
    
    def create_table(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                game_data TEXT NOT NULL,
                last_device TEXT,
                last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def save_user_data(self, user_id, game_data, device_info="unknown"):
        """Сохраняем данные пользователя (работает с любого устройства)"""
        game_json = json.dumps({
            'score': game_data.score,
            'click_power': game_data.click_power,
            'auto_click_power': game_data.auto_click_power,
            'prestige_level': game_data.prestige_level,
            'total_clicks': game_data.total_clicks,
            'bonus_multiplier': game_data.bonus_multiplier,
            'bonus_time': game_data.bonus_time,
            'last_save': datetime.now().isoformat()
        })
        
        self.conn.execute(
            '''INSERT OR REPLACE INTO users 
               (user_id, game_data, last_device, last_sync) 
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)''',
            (user_id, game_json, device_info)
        )
        self.conn.commit()
    
    def load_user_data(self, user_id):
        """Загружаем данные пользователя (работает на любом устройстве)"""
        cursor = self.conn.execute(
            'SELECT game_data FROM users WHERE user_id = ?', 
            (user_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return json.loads(result[0])
        return None

# Инициализируем менеджер пользователей
user_manager = UserManager()

# ===== ИГРОВАЯ ЛОГИКА =====
class ClickerGame:
    def init(self, user_id):
        self.user_id = user_id
        self.score = 0
        self.click_power = 1
        self.auto_click_power = 0
        self.bonus_multiplier = 1
        self.bonus_time = 0
        self.total_clicks = 0
        self.prestige_level = 0
        self.prestige_bonus = 1.0
        self.last_auto_click = time.time()
        self.created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
        
    def click(self):
        """Обработка клика с учетом престиж-бонуса"""
        points = self.click_power * self.bonus_multiplier * self.prestige_bonus
        self.score += points
        self.total_clicks += 1
        return int(points)
        
    def buy_upgrade(self, upgrade_type, index):
        """Покупка улучшений"""
        upgrades = {
            'click': [
                {'cost': 10, 'power': 1, 'name': 'Ручка для кликов'},
                {'cost': 100, 'power': 5, 'name': 'Волшебная мышка'},
                {'cost': 10000, 'power': 50, 'name': 'Квантовый кликер'}
            ],
            'auto': [
                {'cost': 50, 'power': 1, 'name': 'Маленький бот'},
                {'cost': 500, 'power': 5, 'name': 'Ферма кликов'},
                {'cost': 10000, 'power': 50, 'name': 'ИИ Кликер 9000'}
            ],
            'bonus': [
                {'cost': 200, 'multiplier': 2, 'duration': 30, 'name': 'Энергия x2'},
                {'cost': 1000, 'multiplier': 3, 'duration': 20, 'name': 'Безумие x3'},
                {'cost': 5000, 'multiplier': 5, 'duration': 15, 'name': 'БОГ x5'}
                ]
        }
        
        upgrade = upgrades[upgrade_type][index]
        
        if self.score >= upgrade['cost']:
            self.score -= upgrade['cost']
            
            if upgrade_type == 'click':
                self.click_power += upgrade['power']
            elif upgrade_type == 'auto':
                self.auto_click_power += upgrade['power']
            elif upgrade_type == 'bonus':
                self.activate_bonus(upgrade['multiplier'], upgrade['duration'])
                
            return True, upgrade['name']
        return False, upgrade['name']
    
    def activate_bonus(self, multiplier, duration):
        """Активация бонуса"""
        self.bonus_multiplier = multiplier
        self.bonus_time = duration
        
        def bonus_timer():
            remaining = duration
            while remaining > 0:
                time.sleep(1)
                remaining -= 1
                self.bonus_time = remaining
            self.bonus_multiplier = 1
            
        threading.Thread(target=bonus_timer, daemon=True).start()
    
    def can_prestige(self):
        """Проверка возможности престижа"""
        requirement = self.get_prestige_requirement()
        return self.score >= requirement
    
    def get_prestige_requirement(self):
        """Расчет требования для престижа"""
        base_requirement = 1000000
        return base_requirement * (2 ** self.prestige_level)
    
    def get_prestige_progress(self):
        """Прогресс до следующего престижа"""
        requirement = self.get_prestige_requirement()
        progress = (self.score / requirement) * 100
        return min(progress, 100)
    
    def prestige(self):
        """Выполнение престижа"""
        if self.can_prestige():
            requirement = self.get_prestige_requirement()
            old_level = self.prestige_level
            
            self.prestige_level += 1
            self.prestige_bonus = 1.0 + (self.prestige_level * 0.10)
            
            total_earned = self.score
            
            self.score = 0
            self.click_power = 1
            self.auto_click_power = 0
            self.bonus_multiplier = 1
            self.total_clicks = 0
            self.bonus_time = 0
            
            return True, old_level, total_earned, requirement
        return False, self.prestige_level, self.score, self.get_prestige_requirement()

# ===== АВТО-СОХРАНЕНИЕ =====
def auto_save_loop():
    """Фоновая задача авто-сохранения"""
    while True:
        time.sleep(30)
        for user_id, game in user_games.items():
            try:
                user_manager.save_user_data(user_id, game, "auto_save")
            except Exception as e:
                print(f"❌ Ошибка авто-сохранения {user_id}: {e}")

# Запускаем авто-сохранение
save_thread = threading.Thread(target=auto_save_loop, daemon=True)
save_thread.start()

# ===== ТЕЛЕГРАМ КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    device_info = f"tg_{message.from_user.language_code}"
    
    # Загружаем сохраненные данные
    saved_data = user_manager.load_user_data(user_id)
    
    if saved_data:
        # Восстанавливаем игру
        if user_id not in user_games:
            user_games[user_id] = ClickerGame(user_id)
        
        game = user_games[user_id]
        game.score = saved_data.get('score', 0)
        game.click_power = saved_data.get('click_power', 1)
        game.auto_click_power = saved_data.get('auto_click_power', 0)
        game.prestige_level = saved_data.get('prestige_level', 0)
        game.total_clicks = saved_data.get('total_clicks', 0)
        game.bonus_multiplier = saved_data.get('bonus_multiplier', 1)
        game.bonus_time = saved_data.get('bonus_time', 0)
        
        # Обновляем престиж бонус
        game.prestige_bonus = 1.0 + (game.prestige_level * 0.10)
        
        bot.send_message(
            message.chat.id, 
            f"🔄 *Загружен ваш прогресс!*\n"
            f"💎 Очков: {format_number(game.score)}\n"
            f"💪 Сила: {game.click_power}\n"
            f"🤖 Авто-кликов: {game.auto_click_power}/сек\n"
            f"⭐ Престиж: {game.prestige_level}",
            parse_mode='Markdown'
        )
    else:
        # Новый пользователь
        if user_id not in user_games:
            user_games[user_id] = ClickerGame(user_id)
        
        bot.send_message(
            message.chat.id, 
            f"🎮 Привет, {username}! Добро пожаловать в *Мега Кликер*!",
            parse_mode='Markdown'
        )
    
    # Сохраняем состояние
    user_manager.save_user_data(user_id, user_games[user_id], device_info)
    show_main_menu(message)

@bot.message_handler(commands=['sync'])
def sync_command(message):
    """Принудительная синхронизация"""
    user_id = message.from_user.id
    if user_id in user_games:
        user_manager.save_user_data(user_id, user_games[user_id], "manual_sync")
        bot.send_message(message.chat.id, "✅ Прогресс синхронизирован на всех устройствах!")
    else:
        bot.send_message(message.chat.id, "❌ Нет активной игры для синхронизации")

@bot.message_handler(commands=['stats'])
def stats_command(message):
    """Статистика игрока"""
    user_id = message.from_user.id
    if user_id in user_games:
        game = user_games[user_id]
        total_multiplier = game.bonus_multiplier * game.prestige_bonus
        
        stats_text = f"""
📊 *ВАША СТАТИСТИКА* 📊

💎 *Очков:* {format_number(game.score)}
💪 *Сила клика:* {game.click_power}
🤖 *Авто-кликов:* {game.auto_click_power}/сек
🎯 *Множитель:* x{total_multiplier:.1f}
⭐ *Уровень престижа:* {game.prestige_level}
💫 *Престиж бонус:* +{int((game.prestige_bonus - 1) * 100)}%
👆 *Всего кликов:* {format_number(game.total_clicks)}

⏰ *Бонус время:* {game.bonus_time}сек
📅 *Играет с:* {game.created_at}
        """
        bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "❌ Начните игру командой /start")

def show_main_menu(message):
    user_id = message.from_user.id
    if user_id not in user_games:
        user_games[user_id] = ClickerGame(user_id)
    
    game = user_games[user_id]
    total_multiplier = game.bonus_multiplier * game.prestige_bonus
    
    menu_text = f"""
🎮 *МЕГА КЛИКЕР БОТ* 🎮

💎 *Очков:* {format_number(game.score)}
💪 *Сила клика:* {game.click_power}
🤖 *Авто-кликов/сек:* {game.auto_click_power}
🎯 *Множитель:* x{total_multiplier:.1f}
⭐ *Престиж:* {game.prestige_level} (+{int((game.prestige_bonus - 1) * 100)}%)

*Выберите действие:*
    """
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton('👆 КЛИКНУТЬ!', callback_data='click'),
        InlineKeyboardButton('🛠 УЛУЧШЕНИЯ', callback_data='upgrades')
    )
    markup.row(
        InlineKeyboardButton('🌟 ПРЕСТИЖ', callback_data='prestige'),
        InlineKeyboardButton('📊 СТАТИСТИКА', callback_data='stats')
    )
    markup.row(
        InlineKeyboardButton('🔄 СИНХРОНИЗИРОВАТЬ', callback_data='sync')
    )
    
    try:
        bot.edit_message_text(
            menu_text,
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
    except:
        bot.send_message(
            message.chat.id,
            menu_text,
            parse_mode='Markdown',
            reply_markup=markup
        )

def show_upgrades_menu(message, game):
    upgrades_text = f"""
🛠 *МАГАЗИН УЛУЧШЕНИЙ* 🛠

💎 *Ваши очки:* {format_number(game.score)}

*Улучшения клика:*
1. Ручка для кликов (+1) - 10 💎
2. Волшебная мышка (+5) - 100 💎  
3. Квантовый кликер (+50) - 10000 💎
*Авто-кликеры:*
4. Маленький бот (+1/сек) - 50 💎
5. Ферма кликов (+5/сек) - 500 💎
6. ИИ Кликер 9000 (+50/сек) - 10000 💎

*Временные бонусы:*
7. Энергия x2 (30сек) - 200 💎
8. Безумие x3 (20сек) - 1000 💎
9. БОГ x5 (15сек) - 5000 💎
    """
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton('1️⃣', callback_data='buy_click_0'),
        InlineKeyboardButton('2️⃣', callback_data='buy_click_1'),
        InlineKeyboardButton('3️⃣', callback_data='buy_click_2')
    )
    markup.row(
        InlineKeyboardButton('4️⃣', callback_data='buy_auto_0'),
        InlineKeyboardButton('5️⃣', callback_data='buy_auto_1'), 
        InlineKeyboardButton('6️⃣', callback_data='buy_auto_2')
    )
    markup.row(
        InlineKeyboardButton('7️⃣', callback_data='buy_bonus_0'),
        InlineKeyboardButton('8️⃣', callback_data='buy_bonus_1'),
        InlineKeyboardButton('9️⃣', callback_data='buy_bonus_2')
    )
    markup.row(InlineKeyboardButton('🔙 НАЗАД', callback_data='main_menu'))
    
    bot.edit_message_text(
        upgrades_text,
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )

def show_prestige_menu(message, game):
    requirement = game.get_prestige_requirement()
    progress = game.get_prestige_progress()
    can_prestige = game.can_prestige()
    
    prestige_text = f"""
🌟 *СИСТЕМА ПРЕСТИЖА* 🌟

*Текущий уровень:* {game.prestige_level}
*Бонус дохода:* +{int((game.prestige_bonus - 1) * 100)}%

*Следующий престиж:*
Требуется: {format_number(requirement)} очков
Ваш прогресс: {progress:.1f}%
Ваши очки: {format_number(game.score)}

💡 *Престиж сбрасывает прогресс, но дает +10% к доходу навсегда!*

{'🚀 *ВЫ МОЖЕТЕ ВЫПОЛНИТЬ ПРЕСТИЖ!*' if can_prestige else '❌ *Недостаточно очков для престижа*'}
    """
    
    markup = InlineKeyboardMarkup()
    if can_prestige:
        markup.add(InlineKeyboardButton(
            '🚀 ВЫПОЛНИТЬ ПРЕСТИЖ!', 
            callback_data='do_prestige'
        ))
    markup.add(InlineKeyboardButton('🔙 НАЗАД', callback_data='main_menu'))
    
    bot.edit_message_text(
        prestige_text,
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    device_info = f"tg_callback"
    
    if user_id not in user_games:
        user_games[user_id] = ClickerGame(user_id)
    
    game = user_games[user_id]
    
    if call.data == 'click':
        points = game.click()
        bot.answer_callback_query(call.id, f"💎 +{points} очков!")
        user_manager.save_user_data(user_id, game, device_info)
        show_main_menu(call.message)
        
    elif call.data == 'upgrades':
        show_upgrades_menu(call.message, game)
        
    elif call.data == 'prestige':
        show_prestige_menu(call.message, game)
        
    elif call.data == 'stats':
        show_stats_menu(call.message, game)
        
    elif call.data == 'sync':
        user_manager.save_user_data(user_id, game, "manual_sync")
        bot.answer_callback_query(call.id, "✅ Прогресс синхронизирован!")
        show_main_menu(call.message)
        
    elif call.data == 'main_menu':
        show_main_menu(call.message)
        
    elif call.data == 'do_prestige':
        success, old_level, total_earned, requirement = game.prestige()
        if success:
            user_manager.save_user_data(user_id, game, device_info)
            bot.answer_callback_query(call.id, f"🌟 Престиж {game.prestige_level} достигнут!")
            
            bot.send_message(
                call.message.chat.id,
                f"🎉 *ПОЗДРАВЛЯЕМ С ПРЕСТИЖЕМ!* 🎉\n\n"
                f"⭐ Новый уровень: {game.prestige_level}\n"
                f"💫 Бонус дохода: +{int((game.prestige_bonus - 1) * 100)}%\n"
                f"💎 Заработано для престижа: {format_number(total_earned)}\n\n"
                f"_Ваш прогресс сброшен, но бонус остаётся навсегда!_",
                parse_mode='Markdown'
            )
        else:
            bot.answer_callback_query(call.id, "❌ Недостаточно очков для престижа!")
        show_main_menu(call.message)
        
    elif call.data.startswith('buy_'):
        parts = call.data.split('_')
        upgrade_type = parts[1]
        index = int(parts[2])
        
        success, name = game.buy_upgrade(upgrade_type, index)
        if success:
            user_manager.save_user_data(user_id, game, device_info)
            bot.answer_callback_query(call.id, f"✅ Куплено: {name}!")
        else:
            bot.answer_callback_query(call.id, "❌ Недостаточно очков!")
        
        if upgrade_type == 'bonus':
            show_main_menu(call.message)
        else:
            show_upgrades_menu(call.message, game)

def show_stats_menu(message, game):
    total_multiplier = game.bonus_multiplier * game.prestige_bonus
    prestige_bonus_percent = int((game.prestige_bonus - 1) * 100)
    
    stats_text = f"""
📊 *ВАША СТАТИСТИКА* 📊

💎 *Всего очков:* {format_number(game.score)}
💪 *Сила клика:* {game.click_power}
🤖 *Авто-кликов:* {game.auto_click_power}/сек
🎯 *Множитель:* x{total_multiplier:.1f}
⭐ *Уровень престижа:* {game.prestige_level}
💫 *Престиж бонус:* +{prestige_bonus_percent}%
👆 *Всего кликов:* {format_number(game.total_clicks)}

⏰ *Бонус время:* {game.bonus_time}сек
📅 *Играет с:* {game.created_at}
    """
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('🔙 НАЗАД', callback_data='main_menu'))
    
    bot.edit_message_text(
        stats_text,
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )

def format_number(num):
    """Форматирование чисел"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    if num >= 1000:
        return f"{num/1000:.1f}K"
    return str(int(num))

# ===== АВТО-КЛИКЕР =====
def auto_click_loop():
    """Фоновая задача авто-кликера"""
    while True:
        current_time = time.time()
        for user_id, game in user_games.items():
            if game.auto_click_power > 0 and current_time - game.last_auto_click >= 1:
                points = game.auto_click_power * game.bonus_multiplier * game.prestige_bonus
                game.score += points
                game.last_auto_click = current_time
        time.sleep(1)

# Запускаем авто-кликер
auto_click_thread = threading.Thread(target=auto_click_loop, daemon=True)
auto_click_thread.start()

# ===== ЗАПУСК БОТА =====
if name == "main":
    print("🎮 Telegram Кликер Бот с синхронизацией запущен!")
    print("📍 Команды: /start, /stats, /sync")
    print("🌟 Система престижа активна!")
    print("🔄 Синхронизация между устройствами включена!")
    
    bot.polling(none_stop=True)
    