import os
import logging
import sqlite3
import requests
import schedule
import time
import asyncio
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ==================== الإعدادات الأساسية ====================
MAIN_BOT_TOKEN = os.environ.get("MAIN_BOT_TOKEN") or "ضع توكن البوت الرئيسي في متغير البيئة"
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN") or "ضع توكن الادمن في متغير البيئة"
ARCHIVE_CHANNEL = os.environ.get("ARCHIVE_CHANNEL") or "-1003178411340"
ERROR_CHANNEL = os.environ.get("ERROR_CHANNEL") or "-1003091305351"
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS") or "TYy5CnBE3kJ2b7oom3vPhey8PX5mi7GQhd"

DATABASE_PATH = os.path.join(os.getcwd(), "trading_bot.db")

# ==================== خطط الاشتراك ====================
SUBSCRIPTION_PLANS = {
    "bronze": {"name": "🟤 الخطة البرونزية", "price": 100, "days": 3, "profits": "10% - 20%"},
    "silver": {"name": "⚪ الخطة الفضية", "price": 500, "days": 3, "profits": "15% - 25%"},
    "gold": {"name": "🟡 الخطة الذهبية", "price": 1000, "days": 7, "profits": "20% - 35%"},
    "platinum": {"name": "🔵 الخطة البلاتينية", "price": 5000, "days": 15, "profits": "35% - 50%"},
    "diamond": {"name": "🔶 الخطة الماسية", "price": 10000, "days": 30, "profits": "50% - 80%"},
    "royal": {"name": "🟣 الخطة الملكية", "price": 20000, "days": 30, "profits": "حتى 100%"},
    "legendary": {"name": "🟠 الخطة الأسطورية", "price": 50000, "days": 30, "profits": "120% - 150%"}
}

# ==================== إعداد التسجيل ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== قاعدة البيانات ====================
def init_database():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  full_name TEXT, 
                  phone TEXT,
                  country TEXT,
                  balance REAL DEFAULT 0,
                  referral_code TEXT,
                  referred_by INTEGER,
                  subscription_level TEXT,
                  subscription_date DATE,
                  registration_date DATE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  type TEXT,
                  amount REAL,
                  status TEXT,
                  transaction_date DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS referrals
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  referrer_id INTEGER,
                  referred_id INTEGER,
                  commission_earned REAL DEFAULT 0,
                  referral_date DATE)''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def register_user(user_id, full_name, phone, country, referral_code=None):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    user_referral_code = f"REF{user_id}{datetime.now().strftime('%H%M')}"
    referred_by = None
    if referral_code:
        c.execute("SELECT user_id FROM users WHERE referral_code = ?", (referral_code,))
        referrer = c.fetchone()
        if referrer:
            referred_by = referrer[0]
    c.execute('''INSERT OR REPLACE INTO users 
                 (user_id, full_name, phone, country, referral_code, referred_by, registration_date) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (user_id, full_name, phone, country, user_referral_code, referred_by, date.today()))
    conn.commit()
    conn.close()
    if referred_by:
        asyncio.create_task(send_admin_notification(f"🎉 لديك محال جديد!\n👤 الاسم: {full_name}\n🆔 الأيدي: {user_id}"))
    return user_referral_code

def update_user_balance(user_id, amount):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def add_transaction(user_id, transaction_type, amount, status="pending"):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO transactions 
                 (user_id, type, amount, status, transaction_date) 
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id, transaction_type, amount, status, datetime.now()))
    conn.commit()
    conn.close()

async def send_admin_notification(message):
    try:
        admin_app = Application.builder().token(ADMIN_BOT_TOKEN).build()
        await admin_app.bot.send_message(chat_id=ARCHIVE_CHANNEL, text=message)
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار الأدمن: {e}")

async def send_error_notification(error_message):
    try:
        admin_app = Application.builder().token(ADMIN_BOT_TOKEN).build()
        await admin_app.bot.send_message(chat_id=ERROR_CHANNEL, text=f"🚨 خطأ: {error_message}")
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار الخطأ: {e}")

def add_referral_commission(referrer_id, referred_id, amount):
    commission = amount * 0.10
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (commission, referrer_id))
    c.execute('''INSERT INTO referrals 
                 (referrer_id, referred_id, commission_earned, referral_date) 
                 VALUES (?, ?, ?, ?)''',
              (referrer_id, referred_id, commission, date.today()))
    conn.commit()
    conn.close()
    return commission

# ==================== البوت الرئيسي - Start ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_data = get_user_data(user_id)
    if not user_data:
        context.user_data['awaiting_registration'] = True
        await update.message.reply_text(
            f"مرحباً {user_name}! 👋\n"
            "🔥 جاهز تبدأ رحلتك في عالم الأرباح؟\n\n"
            "⚡ مع هذا البوت:\n"
            "• ما تحتاج أي خبرة بالتداول 🧑‍💻\n"
            "• صفقات احترافية تنسخ تلقائياً ✅\n"
            "• نتائج وأرباح تشوفها بنفسك 💵\n\n"
            "🚀 لإكمال التسجيل، يرجى إرسال:\n"
            "1. الاسم الثلاثي\n"
            "2. رقم الواتساب\n"
            "3. البلد\n\n"
            "مثال:\n"
            "محمد أحمد علي\n"
            "966512345678\n"
            "السعودية"
        )
        await send_admin_notification(f"👤 مستخدم جديد دخل البوت: {user_name} (ID: {user_id})")
    else:
        await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    balance = user_data[4] if user_data else 0
    keyboard = [
        [InlineKeyboardButton("💼 خطط الاشتراك", callback_data="subscription_plans")],
        [InlineKeyboardButton("💰 رصيدي", callback_data="check_balance")],
        [InlineKeyboardButton("🎁 ادعو أصدقائك", callback_data="referral_system")],
        [InlineKeyboardButton("💳 سحب الأرباح", callback_data="withdraw_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"مرحباً بعودتك! 👋\n"
        f"💼 محفظتك: {balance:.2f} USDT\n\n"
        "اختر من القائمة:",
        reply_markup=reply_markup
    )

async def handle_user_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_input = update.message.text.strip()
    if 'awaiting_registration' in context.user_data:
        try:
            lines = user_input.split('\n')
            if len(lines) >= 3:
                full_name = lines[0].strip()
                phone = lines[1].strip()
                country = lines[2].strip()
                referral_code = None
                if len(lines) > 3 and lines[3].strip().startswith('REF'):
                    referral_code = lines[3].strip()
                user_referral_code = register_user(user_id, full_name, phone, country, referral_code)
                await update.message.reply_text(
                    f"🎉 تم تسجيلك بنجاح {full_name}!\n\n"
                    f"📋 بياناتك:\n"
                    f"👤 الاسم: {full_name}\n"
                    f"📞 الهاتف: {phone}\n"
                    f"🏳️ البلد: {country}\n"
                    f"🔗 كود دعوتك: {user_referral_code}\n\n"
                    f"🚀 الآن يمكنك اختيار خطة الاشتراك المناسبة لك!"
                )
                await send_admin_notification(
                    f"✅ تسجيل مستخدم جديد\n"
                    f"👤 الاسم: {full_name}\n"
                    f"📞 الهاتف: {phone}\n"
                    f"🏳️ البلد: {country}\n"
                    f"🆔 الأيدي: {user_id}"
                )
                del context.user_data['awaiting_registration']
                await show_main_menu(update, context)
            else:
                await update.message.reply_text(
                    "❌ يرجى إدخال البيانات بالشكل الصحيح:\n\n"
                    "الاسم الثلاثي\n"
                    "رقم الواتساب\n"
                    "البلد\n\n"
                    "مثال:\n"
                    "محمد أحمد علي\n"
                    "966512345678\n"
                    "السعودية"
                )
        except Exception as e:
            await update.message.reply_text("❌ حدث خطأ في التسجيل، يرجى المحاولة مرة أخرى")
            await send_error_notification(f"خطأ في تسجيل المستخدم {user_id}: {e}")

async def show_subscription_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = []
    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['name']} - {plan['price']} USDT",
                callback_data=f"subscribe_{plan_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    plans_text = "💼 خطط الاشتراك المتاحة:\n\n"
    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        plans_text += f"{plan['name']}\n"
        plans_text += f"💰 السعر: {plan['price']} USDT\n"
        plans_text += f"⏳ المدة: {plan['days']} يوم\n"
        plans_text += f"📈 الأرباح: {plan['profits']}\n\n"
    await query.edit_message_text(plans_text, reply_markup=reply_markup)

async def handle_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    plan_id = query.data.split("_")[1]
    plan = SUBSCRIPTION_PLANS[plan_id]
    await query.answer()
    subscription_text = (
        f"🎉 تم اختيار خطتك بنجاح!\n\n"
        f"🔹 الخطة: {plan['name']}\n"
        f"💰 السعر: {plan['price']} USDT\n"
        f"⏳ المدة: {plan['days']} يوم\n"
        f"📊 الأرباح المتوقعة: {plan['profits']}\n\n"
        f"💡 للمتابعة يرجى إتمام عملية الدفع على العنوان التالي:\n"
        f"`{WALLET_ADDRESS}`\n\n"
        f"⚠️ ملاحظة:\n"
        f"• تأكد أن التحويل يتم باستخدام شبكة TRC20 فقط\n"
        f"• سيتم تفعيل اشتراكك خلال 15 دقيقة بعد التأكيد\n\n"
        f"بعد الدفع، اضغط على زر تأكيد الدفع وأرسل صورة التحويل"
    )
    keyboard = [
        [InlineKeyboardButton("📸 تأكيد الدفع وإرسال الإثبات", callback_data=f"confirm_payment_{plan_id}")],
        [InlineKeyboardButton("🔙 رجوع للخطط", callback_data="subscription_plans")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(subscription_text, reply_markup=reply_markup, parse_mode='Markdown')
    user = get_user_data(query.from_user.id)
    user_name = user[1] if user else query.from_user.first_name
    await send_admin_notification(
        f"🔄 طلب اشتراك جديد\n"
        f"👤 المستخدم: {user_name}\n"
        f"🆔 الأيدي: {query.from_user.id}\n"
        f"📋 الخطة: {plan['name']}\n"
        f"💰 المبلغ: {plan['price']} USDT"
    )

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    plan_id = query.data.split("_")[2]
    plan = SUBSCRIPTION_PLANS[plan_id]
    await query.answer()
    await query.edit_message_text(
        f"📸 جاهز لاستلام إثبات الدفع للخطة {plan['name']}\n\n"
        f"💰 المبلغ: {plan['price']} USDT\n\n"
        f"يرجى إرسال صورة إشعار التحويل الآن\n\n"
        f"⚠️ تأكد من ظهور في الصورة:\n"
        f"• المبلغ المحول\n" 
        f"• عنوان المحفظة المرسل إليها\n"
        f"• تاريخ ووقت التحويل"
    )
    context.user_data['awaiting_payment_proof'] = plan_id

async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    user_name = user_data[1] if user_data else update.effective_user.first_name
    if 'awaiting_payment_proof' in context.user_data:
        plan_id = context.user_data['awaiting_payment_proof']
        plan = SUBSCRIPTION_PLANS[plan_id]
        await update.message.reply_text(
            "✅ تم استلام صورة الإثبات بنجاح!\n\n"
            "⏳ جاري مراجعة التحويل وتفعيل اشتراكك...\n"
            "سيصلك إشعار خلال 15 دقيقة كحد أقصى"
        )
        admin_app = Application.builder().token(ADMIN_BOT_TOKEN).build()
        keyboard = [
            [InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"approve_sub_{user_id}_{plan_id}")],
            [InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        caption = (
            f"📨 إشعار تحويل جديد\n"
            f"👤 من: {user_name}\n"
            f"🆔 الأيدي: {user_id}\n"
            f"📋 الخطة: {plan['name']}\n"
            f"💰 المبلغ: {plan['price']} USDT"
        )
        await admin_app.bot.send_photo(
            chat_id=ARCHIVE_CHANNEL,
            photo=update.message.photo[-1].file_id,
            caption=caption,
            reply_markup=reply_markup
        )
        del context.user_data['awaiting_payment_proof']
    else:
        await update.message.reply_text("❌ لم تطلب تأكيد دفع، يرجى اختيار خطة أولاً")

async def show_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    balance = user_data[4] if user_data else 0
    keyboard = [
        [InlineKeyboardButton("💳 سحب الأرباح (24 ساعة)", callback_data="withdraw_profits")],
        [InlineKeyboardButton("🎁 سحب المكافآت (أسبوعي)", callback_data="withdraw_bonus")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"💳 نظام السحب\n\n"
        f"💰 رصيدك الحالي: {balance:.2f} USDT\n\n"
        f"📋 خيارات السحب:\n"
        f"• سحب الأرباح: كل 24 ساعة (25$ - 1000$)\n"
        f"• سحب المكافآت: كل أسبوع (لا حدود)\n\n"
        f"اختر نوع السحب:",
        reply_markup=reply_markup
    )

async def show_referral_system(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    referral_code = user_data[5] if user_data else "غير متوفر"
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
    referral_count = c.fetchone()[0]
    c.execute("SELECT SUM(commission_earned) FROM referrals WHERE referrer_id = ?", (user_id,))
    total_commissions = c.fetchone()[0] or 0
    conn.close()
    referral_text = (
        f"🎁 نظام الدعوة والتوصية\n\n"
        f"💼 كود دعوتك: `{referral_code}`\n\n"
        f"📊 إحصائياتك:\n"
        f"• عدد المدعوين: {referral_count}\n"
        f"• إجمالي العمولات: {total_commissions:.2f} USDT\n\n"
        f"💰 كيف تربح:\n"
        f"• أنت تربح 10% من كل إيداع لأصدقائك\n"
        f"• صديقك يحصل على 15% خصم على أول إيداع\n"
        f"• الأرباح غير محدودة!\n\n"
        f"🔗 رابط الدعوة:\n"
        f"https://t.me/your_bot_username?start={referral_code}\n\n"
        f"📣 شارك الرابط مع أصدقائك واكسب مع كل صديق!"
    )
    keyboard = [
        [InlineKeyboardButton("🔗 نسخ رابط الدعوة", callback_data="copy_referral_link")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(referral_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if str(user_id) not in ["100317841", "763916290"]:
        await update.message.reply_text("❌ غير مصرح لك بالوصول!")
        return
    keyboard = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("💳 طلبات السحب", callback_data="admin_withdrawals")],
        [InlineKeyboardButton("🔔 الإشعارات", callback_data="admin_notifications")],
        [InlineKeyboardButton("⚙️ إدارة المحافظ", callback_data="admin_wallets")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🛠️ لوحة تحكم الأدمن\n\n"
        "اختر الإدارة المطلوبة:",
        reply_markup=reply_markup
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE subscription_level IS NOT NULL")
    subscribed_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE registration_date = ?", (date.today(),))
    new_today = c.fetchone()[0]
    c.execute("SELECT SUM(balance) FROM users")
    total_balance = c.fetchone()[0] or 0
    c.execute("SELECT SUM(amount) FROM transactions WHERE type = 'deposit' AND status = 'completed'")
    total_deposits = c.fetchone()[0] or 0
    c.execute("SELECT SUM(amount) FROM transactions WHERE type = 'withdrawal' AND status = 'completed'")
    total_withdrawals = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM referrals")
    total_referrals = c.fetchone()[0]
    c.execute("SELECT SUM(commission_earned) FROM referrals")
    total_commissions = c.fetchone()[0] or 0
    conn.close()
    stats_text = (
        f"📊 إحصائيات النظام - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"👥 المستخدمين:\n"
        f"• الإجمالي: {total_users} مستخدم\n"
        f"• المشتركين: {subscribed_users} مستخدم\n"
        f"• جدد اليوم: {new_today} مستخدم\n\n"
        f"💰 المالية:\n"
        f"• إجمالي الرصيد: {total_balance:.2f} USDT\n"
        f"• إجمالي الإيداعات: {total_deposits:.2f} USDT\n"
        f"• إجمالي السحبات: {total_withdrawals:.2f} USDT\n\n"
        f"🎁 الإحالات:\n"
        f"• إجمالي الإحالات: {total_referrals}\n"
        f"• إجمالي العمولات: {total_commissions:.2f} USDT\n\n"
        f"🟢 الحالة: النظام يعمل بشكل طبيعي"
    )
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(stats_text, reply_markup=reply_markup)

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, full_name, balance, subscription_level FROM users ORDER BY registration_date DESC LIMIT 10")
    recent_users = c.fetchall()
    conn.close()
    users_text = "👥 آخر 10 مستخدمين:\n\n"
    for user in recent_users:
        user_id, full_name, balance, subscription = user
        sub_text = subscription if subscription else "غير مشترك"
        users_text += f"👤 {full_name}\n🆔 {user_id}\n💼 {balance:.2f}$\n📋 {sub_text}\n\n"
    keyboard = [
        [InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="admin_search_user")],
        [InlineKeyboardButton("📧 رسالة جماعية", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(users_text, reply_markup=reply_markup)

async def approve_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data.split("_")
    user_id = int(data[2])
    plan_id = data[3]
    plan = SUBSCRIPTION_PLANS[plan_id]
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET subscription_level = ?, balance = balance + ? WHERE user_id = ?", 
              (plan_id, plan['price'], user_id))
    c.execute("INSERT INTO transactions (user_id, type, amount, status, transaction_date) VALUES (?, ?, ?, ?, ?)",
              (user_id, "deposit", plan['price'], "completed", datetime.now()))
    conn.commit()
    conn.close()
    await query.answer("✅ تم تفعيل الاشتراك!")
    await query.edit_message_text(f"✅ تم تفعيل اشتراك المستخدم {user_id} بالخطة {plan['name']}")
    try:
        main_app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await main_app.bot.send_message(
            chat_id=user_id,
            text=f"🎉 تم تأكيد اشتراكك بنجاح!\n\n"
                 f"📋 الخطة: {plan['name']}\n"
                 f"💰 الرصيد المضاف: {plan['price']} USDT\n"
                 f"⏳ المدة: {plan['days']} يوم\n\n"
                 f"يمكنك الآن بدء التداول والاستفادة من الخدمة!"
        )
    except Exception as e:
        await send_error_notification(f"خطأ في إرسال إشعار للمستخدم {user_id}: {e}")

async def admin_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    wallet_text = (
        f"💳 إدارة المحافظ\n\n"
        f"📍 المحفظة النشطة:\n"
        f"`{WALLET_ADDRESS}`\n\n"
        f"🌐 الشبكة: TRC20\n"
        f"⏰ آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    keyboard = [
        [InlineKeyboardButton("✏️ تغيير العنوان", callback_data="change_wallet")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(wallet_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    try:
        if data == "back_to_main":
            await show_main_menu(update, context)
        elif data == "back_to_admin":
            await admin_start(update, context)
        elif data == "subscription_plans":
            await show_subscription_plans(update, context)
        elif data == "check_balance":
            user_id = query.from_user.id
            user_data = get_user_data(user_id)
            balance = user_data[4] if user_data else 0
            await query.answer()
            await query.edit_message_text(f"💼 رصيدك الحالي: {balance:.2f} USDT")
        elif data == "referral_system":
            await show_referral_system(update, context)
        elif data == "withdraw_menu":
            await show_withdraw_menu(update, context)
        elif data.startswith("subscribe_"):
            await handle_subscription(update, context)
        elif data.startswith("confirm_payment_"):
            await confirm_payment(update, context)
        elif data.startswith("approve_sub_"):
            await approve_subscription(update, context)
        elif data == "admin_stats":
            await admin_stats(update, context)
        elif data == "admin_users":
            await admin_users(update, context)
        elif data == "admin_wallets":
            await admin_wallets(update, context)
        else:
            await query.answer("⚙️ هذه الخاصية قيد التطوير")
    except Exception as e:
        await query.answer("❌ حدث خطأ، يرجى المحاولة مرة أخرى")
        await send_error_notification(f"خطأ في معالجة الزر {data}: {e}")

def setup_scheduled_reports():
    # استخدم threading للجدولة فقط وليس للـ polling
    import threading
    def run_daily():
        while True:
            schedule.run_pending()
            time.sleep(1)
    schedule.every().day.at("08:00").do(lambda: asyncio.create_task(send_daily_report()))
    schedule.every().hour.do(lambda: asyncio.create_task(send_hourly_report()))
    threading.Thread(target=run_daily, daemon=True).start()

async def send_daily_report():
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE registration_date = ?", (date.today(),))
        new_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM transactions WHERE DATE(transaction_date) = ? AND type = 'deposit'", (date.today(),))
        deposits_today = c.fetchone()[0]
        conn.close()
        report_text = (
            f"📊 التقرير اليومي - {date.today()}\n\n"
            f"👥 مستخدمين جدد: {new_users}\n"
            f"💳 إيداعات اليوم: {deposits_today}\n"
            f"🟢 الحالة: النظام يعمل بشكل طبيعي"
        )
        await send_admin_notification(report_text)
    except Exception as e:
        await send_error_notification(f"خطأ في التقرير اليومي: {e}")

async def send_hourly_report():
    try:
        pass
    except Exception as e:
        await send_error_notification(f"خطأ في التقرير الساعي: {e}")

import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

def main():
    print("🚀 بدء تشغيل نظام التداول الآلي...")
    init_database()
    print("✅ قاعدة البيانات مهيأة")
    setup_scheduled_reports()
    print("✅ التقارير التلقائية جاهزة")
    
    # إنشاء البوتات
    main_app = Application.builder().token(MAIN_BOT_TOKEN).build()
    admin_app = Application.builder().token(ADMIN_BOT_TOKEN).build()
    
    # إضافة handlers للبوت الرئيسي
    main_app.add_handler(CommandHandler("start", start))
    main_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_registration))
    main_app.add_handler(MessageHandler(filters.PHOTO, handle_payment_proof))
    main_app.add_handler(CallbackQueryHandler(handle_buttons))
    
    # إضافة handlers لبوت الإدارة
    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(CommandHandler("admin", admin_start))
    admin_app.add_handler(CallbackQueryHandler(handle_buttons))
    
    print("✅ البوت الرئيسي جاهز - التوكن:", MAIN_BOT_TOKEN[:10] + "...")
    print("✅ بوت الإدارة جاهز - التوكن:", ADMIN_BOT_TOKEN[:10] + "...")
    print("📊 القنوات:")
    print("   📁 الأرشيف:", ARCHIVE_CHANNEL)
    print("   🚨 الأخطاء:", ERROR_CHANNEL)
    print("   💳 المحفظة:", WALLET_ADDRESS[:10] + "...")
    
    # تشغيل البوت الرئيسي فقط (يمكنك التبديل إلى بوت الإدارة)
    print("🔧 تشغيل البوت الرئيسي...")
    main_app.run_polling()

if __name__ == '__main__':
    main()
