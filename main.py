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
logger = logging.getLogger(__name__)

# 🔐 استيراد المتغيرات من البيئة
MAIN_BOT_TOKEN = os.environ.get("MAIN_BOT_TOKEN")
ARCHIVE_CHANNEL = os.environ.get("ARCHIVE_CHANNEL", "-1003178411340")
ERROR_CHANNEL = os.environ.get("ERROR_CHANNEL", "-1003091305351")
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS", "TYy5CnBE3k...")

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
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        admin_text = f"👨‍💼 **إشعار إداري**\n\n{message}\n\n⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text=admin_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ فشل إرسال الإشعار الإداري: {e}")

async def send_error_notification(error_message):
    """إرسال إشعار خطأ إلى قناة الأخطاء"""
    try:
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        error_text = f"🚨 **تقرير خطأ**\n\n{error_message}\n\n⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await app.bot.send_message(
            chat_id=ERROR_CHANNEL,
            text=error_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ فشل إرسال تقرير الخطأ: {e}")

async def send_to_archive(message):
    """إرسال رسالة إلى قناة الأرشيف"""
    try:
        app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await app.bot.send_message(
            chat_id=ARCHIVE_CHANNEL,
            text=message,
            parse_mode='Markdown'
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

# ==================== معالجة تسجيل البيانات ====================
async def handle_user_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة بيانات تسجيل المستخدم"""
    try:
        user_id = update.effective_user.id
        user_input = update.message.text.strip()
        
        if 'awaiting_registration' in context.user_data:
            # تحليل البيانات المدخلة
            lines = user_input.split('\n')
            if len(lines) >= 3:
                full_name = lines[0].strip()
                phone = lines[1].strip()
                country = lines[2].strip()
                
                # الحصول على كود الإحالة إذا وجد
                referral_code = context.user_data.get('referral_code')
                
                # تسجيل المستخدم
                user_referral_code = register_user(user_id, full_name, phone, country, referral_code)
                
                if user_referral_code:
                    # إرسال إشعار تأكيد
                    await update.message.reply_text(
                        f"🎉 تم تسجيلك بنجاح {full_name}!\n\n"
                        f"📋 بياناتك:\n"
                        f"👤 الاسم: {full_name}\n"
                        f"📞 الهاتف: {phone}\n"
                        f"🏳️ البلد: {country}\n"
                        f"🔗 كود دعوتك: {user_referral_code}\n\n"
                        f"🚀 الآن يمكنك اختيار خطة الاشتراك المناسبة لك!"
                    )
                    
                    # إشعار الأدمن بتسجيل جديد
                    await send_admin_notification(
                        f"✅ تسجيل مستخدم جديد\n"
                        f"👤 الاسم: {full_name}\n"
                        f"📞 الهاتف: {phone}\n"
                        f"🏳️ البلد: {country}\n"
                        f"🆔 الأيدي: {user_id}"
                    )
                    
                    # عرض القائمة الرئيسية
                    del context.user_data['awaiting_registration']
                    if 'referral_code' in context.user_data:
                        del context.user_data['referral_code']
                    await show_main_menu(update, context)
                else:
                    await update.message.reply_text("❌ حدث خطأ في التسجيل، يرجى المحاولة مرة أخرى")
                
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
        else:
            await update.message.reply_text("❌ لم تطلب التسجيل، استخدم /start للبدء")
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في التسجيل، يرجى المحاولة مرة أخرى")
        await send_error_notification(f"خطأ في تسجيل المستخدم {user_id}: {e}")

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

# ==================== نظام الإحالة ====================
async def show_referral_system(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض نظام الإحالة"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        user_data = get_user_data(user_id)
        referral_code = user_data[5] if user_data else "غير متوفر"
        
        # حساب الإحالات والأرباح
        conn = sqlite3.connect('trading_bot.db', check_same_thread=False)
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
    except Exception as e:
        logger.error(f"❌ خطأ في عرض نظام الإحالة: {e}")
        await send_error_notification(f"خطأ في عرض نظام الإحالة: {e}")

# ==================== نظام الإدارة - أوامر الأدمن ====================
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بدء أوامر الإدارة"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من صلاحية الأدمن (يمكن إضافة المزيد من الأيدي)
        if str(user_id) not in ["100317841", "763916290"]:  # أضف أيديك هنا
            await update.message.reply_text("❌ غير مصرح لك بالوصول!")
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("💳 طلبات السحب", callback_data="admin_withdrawals")],
            [InlineKeyboardButton("⚙️ إدارة المحافظ", callback_data="admin_wallets")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🛠️ لوحة تحكم الأدمن\n\n"
            "اختر الإدارة المطلوبة:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"❌ خطأ في أمر الأدمن: {e}")
        await send_error_notification(f"خطأ في أمر الأدمن: {e}")

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
        await query.edit_message_text(f"✅ تم تفعيل اشتراك المستخدم {user_id} بالخطة {plan['name']}")
        
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

# ==================== معالجة الأزرار العامة ====================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة جميع الأزرار"""
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

# ==================== نظام الجدولة المحسن ====================
class SchedulerManager:
    def __init__(self, app):
        self.running = False
        self.app = app
        
    async def start_scheduler(self):
        """بدء نظام الجدولة"""
        self.running = True
        while self.running:
            try:
                now = datetime.now()
                
                # التقرير اليومي الساعة 8:00
                if now.hour == 8 and now.minute == 0:
                    await send_daily_report()
                
                # التقرير الساعي
                if now.minute == 0:
                    await send_hourly_report()
                
                # الانتظار لمدة دقيقة قبل الفحص التالي
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ خطأ في الجدولة: {e}")
                await asyncio.sleep(60)
    
    def stop_scheduler(self):
        """إوقف نظام الجدولة"""
        self.running = False

# ==================== التشغيل الرئيسي ====================
async def main():
    """الدالة الرئيسية للتشغيل"""
    print("🚀 بدء تشغيل نظام التداول الآلي...")
    
    # تهيئة قاعدة البيانات
    init_database()
    print("✅ قاعدة البيانات مهيأة")
    
    # إنشاء تطبيق البوت
    app = Application.builder().token(MAIN_BOT_TOKEN).build()
    
    # إضافة handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_registration))
    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_proof))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    
    print("✅ البوت الرئيسي جاهز - التوكن:", MAIN_BOT_TOKEN[:10] + "...")
    print("📊 القنوات:")
    print("   📁 الأرشيف:", ARCHIVE_CHANNEL)
    print("   🚨 الأخطاء والإدارة:", ERROR_CHANNEL)
    print("   💳 المحفظة:", WALLET_ADDRESS[:10] + "...")
    
    # بدء نظام الجدولة في الخلفية
    scheduler = SchedulerManager(app)
    scheduler_task = asyncio.create_task(scheduler.start_scheduler())
    print("✅ التقارير التلقائية جاهزة")
    
    # بدء البوت
print("🎉 البوت شغال الآن!")

try:
    await app.run_polling()
except Exception as e:
    print(f"❌ خطأ في تشغيل البوت: {e}")
finally:
    # تنظيف الموارد بشكل صحيح
    scheduler.stop_scheduler()
    if scheduler_task and not scheduler_task.done():
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

# ==================== التشغيل ====================
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("⏹️ إيقاف النظام...")
    except Exception as e:
        print(f"❌ خطأ في التشغيل: {e}")
