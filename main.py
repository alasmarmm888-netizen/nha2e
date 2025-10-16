import os
import asyncio
import logging
import sqlite3
import time
from datetime import datetime, date
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError

# 🔧 إعدادات التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# أضف هذا السطر ⬇️
logger = logging.getLogger(__name__)

# 🔐 المتغيرات الثابتة مباشرة
MAIN_BOT_TOKEN = "7566859808:AAFHlYo7nVIGDe6jnYIiI1EfsU-HeCntH5E"
ARCHIVE_CHANNEL = "-1003178411340"
ERROR_CHANNEL = "-1003091305351"
WALLET_ADDRESS = "TYy5CnBE3k..."
ADMIN_CHAT_ID = "-1003178411340"
# 📊 خطط الاشتراك
SUBSCRIPTION_PLANS = {
    "basic": {
        "name": "الخطة الأساسية",
        "price": 25,
        "days": 30,
        "profits": "5-10% يومياً"
    },
    "pro": {
        "name": "الخطة المتقدمة",
        "price": 50,
        "days": 30,
        "profits": "10-15% يومياً"
    },
    "vip": {
        "name": "الخطة المميزة",
        "price": 100,
        "days": 30,
        "profits": "15-20% يومياً"
    }
}

# ==================== تهيئة قاعدة البيانات ====================
def init_database():
    """تهيئة قاعدة البيانات والجداول"""
    try:
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()

        # جدول المستخدمين
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                country TEXT,
                balance REAL DEFAULT 0.0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                subscription_level TEXT,
                registration_date DATE,
                is_active INTEGER DEFAULT 1
            )
        ''')

        # جدول المعاملات
        c.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                status TEXT,
                transaction_date TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # جدول الإحالات
        c.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                commission_earned REAL,
                referral_date DATE,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_id) REFERENCES users (user_id)
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("✅ قاعدة البيانات مهيأة بنجاح")
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")

# ==================== دوال قاعدة البيانات ====================
def get_user_data(user_id):
    """جلب بيانات المستخدم"""
    try:
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        return user
    except Exception as e:
        logger.error(f"❌ خطأ في جلب بيانات المستخدم: {e}")
        return None

def register_user(user_id, full_name, phone, country, referral_code=None):
    """تسجيل مستخدم جديد"""
    try:
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()

        # إنشاء كود إحالة فريد
        user_referral_code = f"REF{user_id}{datetime.now().strftime('%H%M')}"

        # البحث عن المحيل إذا كان هناك كود إحالة
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

        # إرسال إشعار للمحيل إذا وجد
        if referred_by:
            asyncio.create_task(notify_referral_signup(referred_by, user_id, full_name))

        return user_referral_code
    except Exception as e:
        logger.error(f"❌ خطأ في تسجيل المستخدم: {e}")
        return None

def update_user_balance(user_id, amount):
    """تحديد رصيد المستخدم"""
    try:
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ خطأ في تحديث الرصيد: {e}")
        return False

def add_transaction(user_id, transaction_type, amount, status="pending"):
    """إضافة معاملة جديدة"""
    try:
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()
        c.execute('''INSERT INTO transactions
                     (user_id, type, amount, status, transaction_date)
                     VALUES (?, ?, ?, ?, ?)''',
                  (user_id, transaction_type, amount, status, datetime.now()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ خطأ في إضافة المعاملة: {e}")
        return False

# ==================== دوال الإشعارات ====================
async def send_admin_notification(message):
    """إرسال إشعار إداري إلى قناة الأخطاء (التي أصبحت قناة الإدارة أيضاً)"""
    try:
        await asyncio.sleep(1)

        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        admin_text = f"👨‍💼 **إشعار إداري**\n\n{message}\n\n⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text=admin_text
        )
    except Exception as e:
        logger.error(f"❌ فشل إرسال الإشعار الإداري: {e}")

async def send_error_notification(error_message):
    """إرسال إشعار خطأ إلى قناة الأخطاء"""
    try:

        await asyncio.sleep(1)

        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        error_text = f"🚨 **تقرير خطأ**\n\n{error_message}\n\n⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text=error_text
        )
    except Exception as e:
        logger.error(f"❌ فشل إرسال تقرير الخطأ: {e}")

async def send_to_archive(message):
    """إرسال رسالة إلى قناة الأرشيف"""
    try:
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await app.bot.send_message(
            chat_id=ARCHIVE_CHANNEL,
            text=message
        )
    except Exception as e:
        logger.error(f"❌ فشل إرسال إلى الأرشيف: {e}")

async def notify_referral_signup(referrer_id, referred_id, referred_name):
    """إشعار المحيل بتسجيل محال جديد"""
    try:
        message = f"🎉 لديك محال جديد!\n👤 الاسم: {referred_name}\n🆔 الأيدي: {referred_id}"
        await send_admin_notification(message)
    except Exception as e:
        logger.error(f"❌ خطأ في إشعار الإحالة: {e}")

# ==================== دوال الإحالة ====================
def add_referral_commission(referrer_id, referred_id, amount):
    """إضافة عمولة الإحالة"""
    try:
        commission = amount * 0.10  # 10% عمولة
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()

        # تحديث رصيد المحيل
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (commission, referrer_id))

        # تسجيل العملية
        c.execute('''INSERT INTO referrals
                     (referrer_id, referred_id, commission_earned, referral_date)
                     VALUES (?, ?, ?, ?)''',
                  (referrer_id, referred_id, commission, date.today()))

        conn.commit()
        conn.close()

        return commission
    except Exception as e:
        logger.error(f"❌ خطأ في إضافة عمولة الإحالة: {e}")
        return 0

# ==================== البوت الرئيسي - Start ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بدء البوت الرئيسي"""
    try:
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name

        # التحقق من كود الإحالة إذا وجد
        referral_code = None
        if context.args and context.args[0].startswith('REF'):
            referral_code = context.args[0]

        # التحقق إذا المستخدم مسجل
        user_data = get_user_data(user_id)

        if not user_data:
            # طلب بيانات التسجيل
            context.user_data['awaiting_registration'] = True
            if referral_code:
                context.user_data['referral_code'] = referral_code

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

            # إشعار الأدمن بمستخدم جديد
            await send_admin_notification(f"👤 مستخدم جديد دخل البوت: {user_name} (ID: {user_id})")
        else:
            # عرض القائمة الرئيسية
            await show_main_menu(update, context)
    except Exception as e:
        logger.error(f"❌ خطأ في أمر start: {e}")
        await send_error_notification(f"خطأ في أمر start: {e}")

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض القائمة الرئيسية"""
    try:
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

        if update.callback_query:
            await update.callback_query.edit_message_text(
                f"مرحباً بعودتك! 👋\n"
                f"💼 محفظتك: {balance:.2f} USDT\n\n"
                "اختر من القائمة:",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"مرحباً بعودتك! 👋\n"
                f"💼 محفظتك: {balance:.2f} USDT\n\n"
                "اختر من القائمة:",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"❌ خطأ في عرض القائمة الرئيسية: {e}")
        await send_error_notification(f"خطأ في عرض القائمة الرئيسية: {e}")
# ==================== نظام المراسلة ====================

# ==================== معالجة تسجيل البيانات ====================
async def handle_user_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل المستخدمين"""
    try:
        user_id = update.effective_user.id
        message_text = update.message.text

        # إذا كان بانتظار المحفظة - معالجتها أولاً والخروج
        if context.user_data.get('awaiting_wallet'):
            await handle_wallet_address(update, context)
            return

        # إذا كان بانتظار التسجيل
        if context.user_data.get('awaiting_registration'):
            lines = message_text.strip().split('\n')
            if len(lines) >= 3:
                name = lines[0].strip()
                phone = lines[1].strip()
                country = lines[2].strip()

                # حفظ في قاعدة البيانات
                conn = sqlite3.connect('trading_bot.db')
                c = conn.cursor()
                c.execute('''
                    INSERT OR REPLACE INTO users
                    (user_id, username, full_name, phone, country, balance, registration_date)
                    VALUES (?, ?, ?, ?, ?, 0, datetime('now'))
                ''', (user_id, update.effective_user.username, name, phone, country))
                conn.commit()
                conn.close()

                # مسح حالة الانتظار
                del context.user_data['awaiting_registration']

                await update.message.reply_text(
                    f"✅ تم تسجيلك بنجاح!\n\n"
                    f"👤 الاسم: {name}\n"
                    f"📞 الهاتف: {phone}\n"
                    f"🌍 البلد: {country}\n\n"
                    f"🚀 الآن يمكنك استخدام البوت بشكل كامل!"
                )

                # إشعار الأدمن مع الربط بالقناة
                await send_admin_notification(
                    f"👤 تسجيل جديد:\n"
                    f"الاسم: {name}\n"
                    f"الهاتف: {phone}\n"
                    f"البلد: {country}\n"
                    f"ID: {user_id}\n"
                    f"@{update.effective_user.username or 'بدون'}"
                )
            else:
                await update.message.reply_text(
                    "❌ يرجى إرسال البيانات بالصيغة الصحيحة:\n\n"
                    "الاسم الثلاثي\nرقم الهاتف\nالبلد\n\n"
                    "مثال:\nمحمد أحمد علي\n966512345678\nالسعودية"
                )
            return

        # إذا لا يوجد حالة انتظار - تحويل الرسالة للإدارة
        await forward_user_messages(update, context)

    except Exception as e:
        logger.error(f"خطأ في التسجيل: {e}")
        try:
            await forward_user_messages(update, context)
        except Exception as e2:
            logger.error(f"خطأ في التحويل: {e2}")
# ==================== عرض خطط الاشتراك ====================
async def show_subscription_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض جميع خطط الاشتراك"""
    try:
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
    except Exception as e:
        logger.error(f"❌ خطأ في عرض خطط الاشتراك: {e}")
        await send_error_notification(f"خطأ في عرض خطط الاشتراك: {e}")

# ==================== معالجة الاشتراك ====================
async def handle_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة طلب الاشتراك"""
    try:
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

        # إشعار الأدمن بطلب اشتراك
        user = get_user_data(query.from_user.id)
        user_name = user[1] if user else query.from_user.first_name
        await send_admin_notification(
            f"🔄 طلب اشتراك جديد\n"
            f"👤 المستخدم: {user_name}\n"
            f"🆔 الأيدي: {query.from_user.id}\n"
            f"📋 الخطة: {plan['name']}\n"
            f"💰 المبلغ: {plan['price']} USDT"
        )
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة الاشتراك: {e}")
        await send_error_notification(f"خطأ في معالجة الاشتراك: {e}")

# ==================== تأكيد الدفع ====================
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأكيد إرسال إثبات الدفع"""
    try:
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
    except Exception as e:
        logger.error(f"❌ خطأ في تأكيد الدفع: {e}")
        await send_error_notification(f"خطأ في تأكيد الدفع: {e}")

# ==================== معالجة صورة التحويل ====================
async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة صورة إثبات الدفع"""
    try:
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

            # إرسال الصورة والإشعار للأدمن
            app = Application.builder().token(MAIN_BOT_TOKEN).build()

            # إعداد زر الموافقة
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

            await app.bot.send_photo(
                chat_id=ERROR_CHANNEL,  # استخدام قناة الأخطاء للإدارة
                photo=update.message.photo[-1].file_id,
                caption=caption,
                reply_markup=reply_markup
            )

            del context.user_data['awaiting_payment_proof']

        else:
            await update.message.reply_text("❌ لم تطلب تأكيد دفع، يرجى اختيار خطة أولاً")
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في معالجة الصورة، يرجى المحاولة مرة أخرى")
        await send_error_notification(f"خطأ في معالجة صورة الدفع: {e}")

# ==================== نظام السحب ====================
async def show_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض قائمة السحب"""
    try:
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
    except Exception as e:
        logger.error(f"❌ خطأ في عرض قائمة السحب: {e}")
        await send_error_notification(f"خطأ في عرض قائمة السحب: {e}")
# ==================== معالجة عنوان المحفظة====================
async def handle_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة عنوان المحفظة مع نظام الإدارة"""
    try:
        user_id = update.effective_user.id
        wallet_address = update.message.text.strip()

        # إرسال "جاري معالجة الطلب" فوراً
        processing_msg = await update.message.reply_text(
            "🔄 جاري معالجة طلبك...\n\n"
            "سيتم مراجعة عنوان المحفظة وتفعيله خلال دقائق."
        )

        # تحقق من عنوان المحفظة
        if len(wallet_address) < 10 or not wallet_address.startswith(('0x', '1', '3', 'bc1')):
            await processing_msg.edit_text(
                "❌ عنوان المحفظة غير صالح. يرجى إرسال عنوان صحيح:"
            )
            return

        # حفظ في قاعدة البيانات
        conn = sqlite3.connect('trading_bot.db')
        c = conn.cursor()
        c.execute(
            'UPDATE users SET wallet_address = ? WHERE user_id = ?',
            (wallet_address, user_id)
        )
        conn.commit()
        conn.close()

        # مسح حالة الانتظار
        del context.user_data['awaiting_wallet']

        await processing_msg.edit_text(
            f"✅ تم استلام عنوان محفظتك بنجاح!\n\n"
            f"📍 العنوان: {wallet_address}\n\n"
            f"🔄 جاري المراجعة من قبل الإدارة...\n"
            f"سيتم إعلامك فور التفعيل."
        )

        # إرسال طلب التحويل للقناة مع الأزرار
        keyboard = [
            [InlineKeyboardButton("✅ تم التحويل", callback_data=f"confirm_transfer:{user_id}")],
            [InlineKeyboardButton("❌ تم الرفض", callback_data=f"reject_transfer:{user_id}")],
            [InlineKeyboardButton("📩 إرسال رسالة", callback_data=f"message_user:{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🔄 طلب تحويل جديد:\n\n"
                 f"👤 المستخدم: {user_id}\n"
                 f"📛 الاسم: {update.effective_user.first_name}\n"
                 f"🔗 المستخدم: @{update.effective_user.username or 'بدون'}\n"
                 f"📍 المحفظة: {wallet_address}\n\n"
                 f"⏰ الوقت: {update.message.date}",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"خطأ في حفظ المحفظة: {e}")
        await update.message.reply_text("❌ حدث خطأ في حفظ المحفظة. حاول مرة أخرى.")
    except Exception as e:
        print(f"❌ خطأ في معالجة طلب السحب: {e}")
        await update.message.reply_text("❌ حدث خطأ في معالجة طلب السحب. يرجى المحاولة مرة أخرى.")
async def handle_approve_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """موافقة الأدمن على السحب"""
    try:
        query = update.callback_query
        data = query.data.split('_')
        user_id = int(data[2])
        amount = float(data[3])

        # خصم المبلغ بعد الموافقة
        conn = sqlite3.connect('trading_bot.db')
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        c.execute("UPDATE withdraw_requests SET status = 'approved' WHERE user_id = ? AND status = 'pending'", (user_id,))
        conn.commit()
        conn.close()

        # إشعار المستخدم
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await app.bot.send_message(
            chat_id=user_id,
            text=f"✅ تمت الموافقة على سحبك!\n\n"
                 f"💰 المبلغ: {amount} USDT\n"
                 f"💳 تم تحويل المبلغ لمحفظتك\n"
                 f"⏰ قد يستغرق التحويل 2-24 ساعة\n\n"
                 f"شكراً لاستخدامك خدماتنا! 🎉"
        )

        await query.edit_message_text(
            f"✅ تمت الموافقة على سحب المستخدم {user_id}\n"
            f"💰 المبلغ: {amount} USDT\n\n"
            f"📞 تم إعلام المستخدم بالتحويل."
        )

    except Exception as e:
        print(f"❌ خطأ في الموافقة على السحب: {e}")

async def handle_reject_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رفض الأدمن للسحب"""
    try:
        query = update.callback_query
        data = query.data.split('_')
        user_id = int(data[2])
        amount = float(data[3])

        # تحديث حالة الطلب فقط (بدون خصم)
        conn = sqlite3.connect('trading_bot.db')
        c = conn.cursor()
        c.execute("UPDATE withdraw_requests SET status = 'rejected' WHERE user_id = ? AND status = 'pending'", (user_id,))
        conn.commit()
        conn.close()

        # إشعار المستخدم
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await app.bot.send_message(
            chat_id=user_id,
            text=f"❌ تم رفض طلب السحب\n\n"
                 f"💰 المبلغ: {amount} USDT\n"
                 f"💳 لم يتم خصم أي مبلغ من رصيدك\n\n"
                 f"📞 للاستفسار، تواصل مع الدعم."
        )

        await query.edit_message_text(
            f"❌ تم رفض سحب المستخدم {user_id}\n"
            f"💰 المبلغ: {amount} USDT\n\n"
            f"💳 لم يتم خصم الرصيد."
        )

    except Exception as e:
        print(f"❌ خطأ في رفض السحب: {e}")

async def handle_withdraw_profits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة سحب الأرباح"""
    try:
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        user_data = get_user_data(user_id)
        balance = user_data[4] if user_data else 0

        # التحقق من الحد الأدنى
        if balance < 25:
            await query.edit_message_text(
                f"❌ لا يمكن السحب\n\n"
                f"💰 رصيدك الحالي: {balance:.2f} USDT\n"
                f"📊 الحد الأدنى للسحب: 25 USDT\n\n"
                f"💡 استمر في التداول لتجميع الأرباح!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع", callback_data="withdraw_menu")]
                ])
            )
            return

        # عرض خيارات السحب
        keyboard = [
            [InlineKeyboardButton("25 USDT", callback_data="withdraw_amount_25")],
            [InlineKeyboardButton("50 USDT", callback_data="withdraw_amount_50")],
            [InlineKeyboardButton("100 USDT", callback_data="withdraw_amount_100")],
            [InlineKeyboardButton("250 USDT", callback_data="withdraw_amount_250")],
            [InlineKeyboardButton("500 USDT", callback_data="withdraw_amount_500")],
            [InlineKeyboardButton("1000 USDT", callback_data="withdraw_amount_1000")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="withdraw_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"💳 سحب الأرباح\n\n"
            f"💰 رصيدك الحالي: {balance:.2f} USDT\n"
            f"⏰ مدة المعالجة: 24 ساعة\n\n"
            f"📊 اختر مبلغ السحب:",
            reply_markup=reply_markup
        )

    except Exception as e:
        print(f"❌ خطأ في سحب الأرباح: {e}")

async def handle_withdraw_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة سحب المكافآت"""
    try:
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        user_data = get_user_data(user_id)
        balance = user_data[4] if user_data else 0

        # طلب معلومات المحفظة
        context.user_data['awaiting_wallet'] = True
        context.user_data['withdraw_type'] = 'bonus'

        await query.edit_message_text(
            f"🎁 سحب المكافآت\n\n"
            f"💰 رصيدك الحالي: {balance:.2f} USDT\n"
            f"⏰ مدة المعالجة: 48 ساعة\n\n"
            f"💳 الرجاء إرسال عنوان محفظتك USDT (TRC20):\n\n"
            f"📝 مثال:\n"
            f"TYy5CnBE3k6g5aNZhTNLX1WEnLk6fQ5Xz2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="withdraw_menu")]
            ])
        )

    except Exception as e:
        print(f"❌ خطأ في سحب المكافآت: {e}")

async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة مبلغ السحب المحدد"""
    try:
        query = update.callback_query
        await query.answer()

        data = query.data
        amount = int(data.split('_')[2])  # withdraw_amount_100 → 100

        user_id = query.from_user.id
        user_data = get_user_data(user_id)
        balance = user_data[4] if user_data else 0

        if balance < amount:
            await query.answer(f"❌ رصيدك غير كافي", show_alert=True)
            return

        # طلب معلومات المحفظة
        context.user_data['awaiting_wallet'] = True
        context.user_data['withdraw_type'] = 'profits'
        context.user_data['withdraw_amount'] = amount

        await query.edit_message_text(
            f"💳 تأكيد السحب\n\n"
            f"📊 المبلغ: {amount} USDT\n"
            f"💰 الرصيد بعد السحب: {balance - amount:.2f} USDT\n"
            f"⏰ مدة المعالجة: 24 ساعة\n\n"
            f"💳 الرجاء إرسال عنوان محفظتك USDT (TRC20):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="withdraw_profits")]
            ])
        )
    except Exception as e:
        print(f"❌ خطأ في معالجة مبلغ السحب: {e}")

async def handle_approve_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """موافقة الأدمن على السحب"""
    try:
        query = update.callback_query
        await query.answer("✅ تمت الموافقة على السحب")

        # مجرد تأكيد بسيط
        await query.edit_message_text("✅ تمت الموافقة على طلب السحب بنجاح!")

    except Exception as e:
        print(f"❌ خطأ في الموافقة على السحب: {e}")

async def handle_reject_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رفض الأدمن للسحب"""
    try:
        query = update.callback_query
        await query.answer("❌ تم رفض السحب")

        # مجرد تأكيد بسيط
        await query.edit_message_text("❌ تم رفض طلب السحب!")

    except Exception as e:
        print(f"❌ خطأ في رفض السحب: {e}")
# ==================== نظام الإدارة - أوامر الأدمن ====================


# ==================== إحصائيات الأدمن ====================
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض إحصائيات النظام"""
    try:
        query = update.callback_query
        await query.answer()

        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()

        # إحصائيات المستخدمين
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE subscription_level IS NOT NULL")
        subscribed_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE registration_date = ?", (date.today(),))
        new_today = c.fetchone()[0]

        # إحصائيات مالية
        c.execute("SELECT SUM(balance) FROM users")
        total_balance = c.fetchone()[0] or 0

        c.execute("SELECT SUM(amount) FROM transactions WHERE type = 'deposit' AND status = 'completed'")
        total_deposits = c.fetchone()[0] or 0

        c.execute("SELECT SUM(amount) FROM transactions WHERE type = 'withdrawal' AND status = 'completed'")
        total_withdrawals = c.fetchone()[0] or 0

        # إحصائيات الإحالة
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
    except Exception as e:
        logger.error(f"❌ خطأ في عرض إحصائيات الأدمن: {e}")
        await send_error_notification(f"خطأ في عرض إحصائيات الأدمن: {e}")

# ==================== إدارة المستخدمين ====================
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إدارة المستخدمين"""
    try:
        query = update.callback_query
        await query.answer()

        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
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
    except Exception as e:
        logger.error(f"❌ خطأ في إدارة المستخدمين: {e}")
        await send_error_notification(f"خطأ في إدارة المستخدمين: {e}")

# ==================== تأكيد الاشتراكات من الأدمن ====================
async def approve_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأكيد اشتراك من الأدمن"""
    try:
        query = update.callback_query
        data = query.data.split("_")
        user_id = int(data[2])
        plan_id = data[3]
        plan = SUBSCRIPTION_PLANS[plan_id]

        # تحديث حالة المستخدم
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("UPDATE users SET subscription_level = ?, balance = balance + ? WHERE user_id = ?",
                  (plan_id, plan['price'], user_id))

        # إضافة المعاملة
        c.execute("INSERT INTO transactions (user_id, type, amount, status, transaction_date) VALUES (?, ?, ?, ?, ?)",
                  (user_id, "deposit", plan['price'], "completed", datetime.now()))
        conn.commit()
        conn.close()

        await query.answer("✅ تم تفعيل الاشتراك!")
        await context.bot.send_message(
           chat_id=query.message.chat_id,
            text=f"✅ تم تفعيل اشتراك المستخدم {user_id} بالخطة {plan['name']}")

        # إرسال إشعار للمستخدم
        try:
            app = Application.builder().token(MAIN_BOT_TOKEN).build()
            await app.bot.send_message(
                chat_id=user_id,
                text=f"🎉 تم تأكيد اشتراكك بنجاح!\n\n"
                     f"📋 الخطة: {plan['name']}\n"
                     f"💰 الرصيد المضاف: {plan['price']} USDT\n"
                     f"⏳ المدة: {plan['days']} يوم\n\n"
                     f"يمكنك الآن بدء التداول والاستفادة من الخدمة!"
            )
        except Exception as e:
            await send_error_notification(f"خطأ في إرسال إشعار للمستخدم {user_id}: {e}")
    except Exception as e:
        logger.error(f"❌ خطأ في تأكيد الاشتراك: {e}")
        await send_error_notification(f"خطأ في تأكيد الاشتراك: {e}")

# ==================== نظام إدارة المحافظ ====================
async def admin_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إدارة محافظ الاستلام"""
    try:
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
    except Exception as e:
        logger.error(f"❌ خطأ في إدارة المحافظ: {e}")
        await send_error_notification(f"خطأ في إدارة المحافظ: {e}")

# ===================="""إرسال لوحة التحكم إلى قناة الإدارة"""===============

async def send_admin_panel_to_channel():
    """إرسال لوحة التحكم إلى قناة الإدارة"""
    try:
        app = Application.builder().token(MAIN_BOT_TOKEN).build()

        keyboard = [
            [InlineKeyboardButton("📩 المراسلة", callback_data="messaging_system")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 آخر المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("💳 طلبات الانتظار", callback_data="admin_pending")],
            [InlineKeyboardButton("🔄 تحديث اللوحة", callback_data="admin_refresh")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text="🛠️ **لوحة تحكم الأدمن**\n\nاختر الإدارة المطلوبة:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ خطأ في إرسال لوحة التحكم: {e}")

async def admin_pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض طلبات الانتظار"""
    query = update.callback_query
    await query.answer()

    # جلب طلبات الانتظار من قاعدة البيانات
    conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE status = 'pending'")
    pending_requests = c.fetchall()
    conn.close()

    if pending_requests:
        text = "📋 طلبات الانتظار:\n\n"
        for req in pending_requests:
            text += f"🆔 {req[1]} | 💰 {req[3]} USDT | 📝 {req[2]}\n"
    else:
        text = "✅ لا توجد طلبات في الانتظار"

    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_stats")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup)
# ==================== معالجة الأزرار العامة ====================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة جميع الأزرار"""
    query = update.callback_query
    data = query.data

    try:
        await query.answer()
        print(f"🔘 زر مضغوط: {data}")

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
            await query.edit_message_text(f"💼 رصيدك الحالي: {balance:.2f} USDT")

        elif data == "referral_system":
            await show_referral_system(update, context)

        elif data == "withdraw_menu":
            await show_withdraw_menu(update, context)

        # ⬇️⬇️⬇️ أضف هذا القسم ⬇️⬇️⬇️
        elif data == "withdraw_profits":
            await handle_withdraw_profits(update, context)

        elif data == "withdraw_bonus":
            await handle_withdraw_bonus(update, context)

        elif data.startswith("withdraw_amount_"):
            await handle_withdraw_amount(update, context)

        elif data.startswith("approve_withdraw_"):
            await handle_approve_withdraw(update, context)

        elif data.startswith("reject_withdraw_"):
            await handle_reject_withdraw(update, context)
        # ⬆️⬆️⬆️ نهاية الإضافة ⬆️⬆️⬆️

        elif data == "copy_referral_link":
            user_id = query.from_user.id
            referral_link = f"https://t.me/Arba7Saudi_bot?start=REF{user_id}"
            await query.answer(f"✅ تم نسخ الرابط:\n{referral_link}", show_alert=True)

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

        elif data.startswith("reply_"):
            user_id = data.split("_")[1]
            context.user_data['replying_to'] = user_id
            await query.edit_message_text(
                f"📩 جاهز للرد على المستخدم {user_id}\n\nأرسل رسالة الرد الآن:"
            )

        elif data == "messaging_system":
            await show_messaging_system(update, context)

        elif data == "admin_pending":
            await admin_pending_requests(update, context)

        elif data == "admin_refresh":
            await send_admin_panel_to_channel()
            await query.answer("✅ تم تحديث اللوحة")

        else:
            await query.answer("⚙️ هذه الخاصية قيد التطوير")

    except Exception as e:
        print(f"❌ خطأ في معالجة الزر {data}: {e}")
        await query.answer("❌ حدث خطأ، يرجى المحاولة مرة أخرى")

async def handle_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار الإدارة في القناة"""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = int(data.split(":")[1])

    if data.startswith("confirm_transfer:"):
        # زر "تم التحويل"
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ تم تحويل المبلغ بنجاح!\n\n"
                 "شكراً لاستخدامك خدماتنا. يمكنك متابعة رصيدك من خلال الأمر /balance"
        )

        # تحديث الرسالة في القناة
        await query.edit_message_text(
            text=f"✅ تم التحويل للمستخدم: {user_id}\n\n"
                 f"بواسطة: {query.from_user.first_name}",
            reply_markup=None
        )

    elif data.startswith("reject_transfer:"):
        # زر "تم الرفض"
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ تم رفض طلب السحب\n\n"
                 "يرجى المحاولة لاحقاً أو التواصل مع الدعم."
        )

        # تحديث الرسالة في القناة
        await query.edit_message_text(
            text=f"❌ تم رفض طلب المستخدم: {user_id}\n\n"
                 f"بواسطة: {query.from_user.first_name}",
            reply_markup=None
        )

    elif data.startswith("message_user:"):
        # زر "إرسال رسالة" - نطلب من الأدمن إدخال الرسالة
        context.user_data['awaiting_user_message'] = user_id
        await query.message.reply_text(
            f"أدخل الرسالة التي تريد إرسالها للمستخدم {user_id}:"
        )
# ==================== التقارير التلقائية ====================
async def send_daily_report():
    """إرسال تقرير يومي"""
    try:
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
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
    """إرسال تقرير ساعي"""
    try:
        # يمكنك إضافة إحصائيات ساعية هنا
        report_text = f"🕐 تقرير ساعي - {datetime.now().strftime('%H:%M')}\nالنظام يعمل بشكل طبيعي ✅"
        await send_admin_notification(report_text)
    except Exception as e:
        await send_error_notification(f"خطأ في التقرير الساعي: {e}")

# ==================== نظام الجدولة البسيط ====================
async def scheduler_background():
    """جدولة بسيطة في الخلفية"""
    while True:
        try:
            now = datetime.now()

            # التقرير اليومي الساعة 8:00
            if now.hour == 8 and now.minute == 0:
                await send_daily_report()

            # التقرير الساعي
            if now.minute == 0:
                await send_hourly_report()

            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"❌ خطأ في الجدولة: {e}")
            await asyncio.sleep(60)
# ==================== دوال نظام المراسلة (خارج main) ====================
# ==================== نظام المراسلة ====================
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ردود الأدمن من القناة للمستخدمين"""
    try:
        print(f"🔔 رسالة من القناة للرد: {update.message.text}")

        # إذا كان في مستخدم محدد للرد
        if 'replying_to' in context.user_data:
            target_user_id = context.user_data['replying_to']
            admin_message = update.message.text

            print(f"📤 جاري إرسال رد للمستخدم: {target_user_id}")

            # إرسال الرد للمستخدم
            app = Application.builder().token(MAIN_BOT_TOKEN).build()
            await app.bot.send_message(
                chat_id=target_user_id,
                text=f"📬 رسالة من الإدارة:\n\n{admin_message}"
            )

            await update.message.reply_text(f"✅ تم إرسال الرد للمستخدم {target_user_id}")

            # مسح المستخدم من الذاكرة بعد الرد
            del context.user_data['replying_to']

        else:
            print("❌ لا يوجد مستخدم محدد للرد")
            await update.message.reply_text(
                "❌ لم يتم تحديد مستخدم للرد\n\n"
                "📝 الطريقة الصحيحة:\n"
                "1. اضغط على زر 'رد على المستخدم' في الرسالة\n"
                "2. اكتب رسالة الرد\n"
                "3. سيتم إرسالها تلقائياً"
            )

    except Exception as e:
        print(f"❌ خطأ في handle_admin_reply: {e}")
        await update.message.reply_text(f"❌ فشل إرسال الرد: {e}")
async def forward_user_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحويل رسائل المستخدمين للقناة"""
    try:
        # تجاهل الرسائل من القناة نفسها
        if update.effective_chat.id == int(ERROR_CHANNEL):
            return

        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "مستخدم"
        username = update.effective_user.username or "بدون معرف"

        # تجاهل أوامر البوت
        if update.message.text and update.message.text.startswith('/'):
            return

        # الحصول على نص الرسالة بشكل آمن
        message_text = ""
        if update.message.text:
            message_text = update.message.text
        elif update.message.caption:
            message_text = update.message.caption
        else:
            message_text = "📎 رسالة ميديا"

        print(f"📩 رسالة من مستخدم: {user_name} ({user_id}) - {message_text}")

        # زر الرد على المستخدم
        keyboard = [
            [InlineKeyboardButton(f"📩 رد على {user_name}", callback_data=f"reply_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # إرسال الرسالة للقناة
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text=f"📬 رسالة جديدة:\n\n"
                 f"👤 الاسم: {user_name}\n"
                 f"🆔 المعرف: @{username}\n"
                 f"🔢 ID: {user_id}\n\n"
                 f"💬 الرسالة:\n{message_text}",
            reply_markup=reply_markup
        )

    except Exception as e:
        print(f"❌ خطأ في forward_user_messages: {e}")
# ===================عرض نظام المراسلة  =================
async def show_messaging_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض نظام المراسلة"""
    try:
        query = update.callback_query
        await query.answer()

        text = "📩 نظام المراسلة\n\n"
        text += "• جميع رسائل المستخدمين تصل هنا تلقائياً\n"
        text += "• اضغط على 'رد على المستخدم' في أي رسالة\n"
        text += "• اكتب رسالة الرد وسيتم إرسالها\n\n"
        text += "💡 يمكنك أيضاً استخدام:\n"
        text += "/broadcast نص_الرسالة ← للجميع\n"
        text += "/send user_id الرسالة ← لمستخدم"

        keyboard = [
            [InlineKeyboardButton("🔄 تحديث", callback_data="messaging_system")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception as e:
        print(f"❌ خطأ في show_messaging_system: {e}")

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء لوحة الأدمن"""
    try:
        query = update.callback_query
        await query.answer()

        keyboard = [
            [InlineKeyboardButton("📩 المراسلة", callback_data="messaging_system")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("🔄 تحديث", callback_data="admin_refresh")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🛠️ **لوحة تحكم الأدمن**\n\nاختر الإدارة المطلوبة:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"❌ خطأ في admin_start: {e}")

async def handle_admin_to_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل الأدمن للمستخدمين"""
    if 'awaiting_user_message' in context.user_data:
        user_id = context.user_data['awaiting_user_message']
        admin_message = update.message.text

        try:
            # إرسال الرسالة للمستخدم
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📩 رسالة من الإدارة:\n\n{admin_message}"
            )

            # تأكيد للإدمن
            await update.message.reply_text(
                f"✅ تم إرسال الرسالة للمستخدم {user_id}"
            )

            # مسح حالة الانتظار
            del context.user_data['awaiting_user_message']

        except Exception as e:
            await update.message.reply_text(
                f"❌ فشل إرسال الرسالة: {e}"
            )
# ==================== التشغيل الرئيسي ====================
# ==================== التشغيل ====================
# ==================== نظام الإحالة ====================

def init_referral_system():
    """تهيئة نظام الإحالة"""
    conn = sqlite3.connect('trading_bot.db')
    c = conn.cursor()

    # إنشاء جدول referrals إذا غير موجود
    c.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            commission_earned DECIMAL(10,2) DEFAULT 0,
            referral_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # إضافة حقل referral_code لجدول users إذا غير موجود
    try:
        c.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        print("✅ تم إضافة حقل referral_code")
    except sqlite3.OperationalError:
        pass  # الحقل موجود مسبقاً

    conn.commit()
    conn.close()
    print("✅ نظام الإحالة مهيأ")

def get_referral_stats(user_id):
    """جلب إحصائيات الإحالة"""
    try:
        conn = sqlite3.connect('trading_bot.db')
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        referral_count = c.fetchone()[0]

        c.execute("SELECT SUM(commission_earned) FROM referrals WHERE referrer_id = ?", (user_id,))
        result = c.fetchone()[0]
        total_commissions = result if result is not None else 0

        conn.close()
        return referral_count, total_commissions

    except Exception as e:
        print(f"❌ خطأ في جلب إحصائيات الإحالة: {e}")
        return 0, 0

async def show_referral_system(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض نظام الإحالة"""
    try:
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        referral_code = f"REF{user_id}"

        # ⬇️ أولاً جرب هذا الرابط البسيط
        bot_username = "Arba7Saudi_bot"  # غير هذا لاسم بوتك الصحيح
        referral_link = f"https://t.me/{bot_username}?start={referral_code}"

        # عرض الرابط للمستخدم للتأكد
        referral_text = f"""🎁 <b>نظام الدعوة والتوصية</b>

💼 <b>كود دعوتك:</b> <code>{referral_code}</code>

🔗 <b>رابط الدعوة:</b>
<code>{referral_link}</code>

📣 <b>كيف تستخدم:</b>
1. انسخ الرابط أعلاه 📋
2. أرسله لأصدقائك 📤
3.عندما ينضم صديق، ستحصل على عمولة 10% من ايداعه 💰"""
        keyboard = [
            [InlineKeyboardButton("📋 نسخ الرابط", callback_data="copy_referral_link")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            referral_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    except Exception as e:
        print(f"❌ خطأ في عرض نظام الإحالة: {e}")
# ==================== اختبار ===============
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر الاختبار"""
    await update.message.reply_text("✅ البوت شغال بشكل طبيعي!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المساعدة"""
    help_text = """
🤖 **أوامر البوت:**

/start - بدء استخدام البوت
/test - اختبار حالة البوت
/help - عرض هذه المساعدة

📱 **للمستخدمين:**
• أرسل بياناتك للتسجيل
• أرسل صورة إثبات الدفع
• استخدم الأزرار في القائمة

🛠️ **للمشرفين:**
/broadcast - إرسال رسالة جماعية
/send - إرسال رسالة لمستخدم محدد
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات البوت"""
    # التحقق من صلاحية الأدمن
    user_id = update.effective_user.id
    if str(user_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط!")
        return

    conn = sqlite3.connect('trading_bot.db')
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM referrals")
    total_referrals = c.fetchone()[0]

    c.execute("SELECT SUM(balance) FROM users")
    total_balance = c.fetchone()[0] or 0

    conn.close()

    stats_text = f"""
📊 **إحصائيات البوت:**

👥 المستخدمين: {total_users}
🎁 الإحالات: {total_referrals}
💰 إجمالي الأرصدة: {total_balance:.2f} USDT

🟢 البوت شغال بشكل طبيعي
    """
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def admin_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض آخر المستخدمين"""
    user_id = update.effective_user.id
    if str(user_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط!")
        return

    conn = sqlite3.connect('trading_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, registration_date FROM users ORDER BY id DESC LIMIT 10")
    users = c.fetchall()
    conn.close()

    if users:
        text = "👥 **آخر 10 مستخدمين:**\n\n"
        for user in users:
            text += f"🆔 {user[0]} | 👤 @{user[1] or 'بدون'} | 📅 {user[2][:10]}\n"
    else:
        text = "❌ لا يوجد مستخدمين مسجلين"

    await update.message.reply_text(text, parse_mode='Markdown')
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الأخطاء العامة"""
    try:
        # تسجيل الخطأ
        error_msg = f"❌ خطأ غير متوقع: {context.error}"
        print(error_msg)

        # إرسال تقرير الخطأ لقناة الإدارة
        error_message = f"""
🚨 **تقرير خطأ**

📝 الخطأ: {str(context.error)[:200]}
⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """

        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text=error_message,
            parse_mode='Markdown'
        )

    except Exception as e:
        # إذا فشل إرسال تقرير الخطأ
        print(f"❌ فشل في معالجة الخطأ: {e}")

async def send_error_notification(error_message: str):
    """إرسال إشعار خطأ لقناة الإدارة"""
    try:
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text=f"🚨 **تقرير خطأ**\n\n{error_message}",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"❌ فشل إرسال إشعار الخطأ: {e}")
# ==================== التشغيل الرئيسي ====================
if __name__ == "__main__":
    # تهيئة أنظمة البوت
    init_referral_system()
    print("✅ أنظمة البوت مهيأة")

    app = Application.builder().token(MAIN_BOT_TOKEN).build()

    # إضافة handlers الأساسية فقط
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", admin_stats_command))
    app.add_handler(CommandHandler("users", admin_users_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_registration))
    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_proof))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & filters.Chat(chat_id=int(ERROR_CHANNEL)), handle_admin_reply))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_user_messages))
    app.add_error_handler(error_handler)
    app.add_handler(CallbackQueryHandler(handle_admin_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_to_user_message))

    print("🎉 البوت شغال الآن!")
    app.run_polling(
        drop_pending_updates=True,
        close_loop=False
    )
