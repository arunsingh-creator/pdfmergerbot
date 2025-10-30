import os
import logging
import tempfile
from typing import Optional
import fitz
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from threading import Thread
from flask import Flask
import asyncio

# Flask web server to keep Render happy
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "PDF Merger Bot is running! 🤖"

@flask_app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)


API_ID = os.getenv("API_ID", "YOUR_API_ID")
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
BATCH_TIMEOUT = 30

if API_ID == "YOUR_API_ID" or API_HASH == "YOUR_API_HASH" or BOT_TOKEN == "YOUR_BOT_TOKEN":
    raise ValueError("Please set API_ID, API_HASH, and BOT_TOKEN environment variables!")


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


user_sessions = {}

class PDFInfo:
    """Store PDF metadata"""
    def __init__(self, path: str, filename: str, pages: int, size: float, order: int):
        self.path = path
        self.filename = filename
        self.pages = pages
        self.size = size
        self.order = order

class UserSession:
    """Manages user's PDF editing session"""
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.pdfs = []
        self.state = "idle"
        self.temp_data = {}
        self.is_merged = False
        self.batch_mode = False
        self.processing_batch = False
    
    def add_pdf(self, pdf_info: PDFInfo):
        self.pdfs.append(pdf_info)
        self.is_merged = False
    
    def swap_pdfs(self, idx1: int, idx2: int):
        if 0 <= idx1 < len(self.pdfs) and 0 <= idx2 < len(self.pdfs):
            self.pdfs[idx1], self.pdfs[idx2] = self.pdfs[idx2], self.pdfs[idx1]
            return True
        return False
    
    def move_pdf(self, from_idx: int, to_idx: int):
        if 0 <= from_idx < len(self.pdfs) and 0 <= to_idx < len(self.pdfs):
            pdf = self.pdfs.pop(from_idx)
            self.pdfs.insert(to_idx, pdf)
            return True
        return False
    
    def clear(self):
        for pdf_info in self.pdfs:
            try:
                if os.path.exists(pdf_info.path):
                    os.remove(pdf_info.path)
            except Exception as e:
                logger.error(f"Failed to remove {pdf_info.path}: {e}")
        self.pdfs.clear()
        self.temp_data.clear()
        self.state = "idle"
        self.is_merged = False
        self.batch_mode = False
        self.processing_batch = False


def get_session(user_id: int) -> UserSession:
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]


def create_main_menu(pdf_count: int, is_merged: bool = False, batch_mode: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    
    if is_merged:
        buttons.extend([
            [InlineKeyboardButton("📥 Download Merged PDF", callback_data="finish")],
            [InlineKeyboardButton("✂️ Remove Pages", callback_data="remove_page")],
            [InlineKeyboardButton("🔄 Start Over", callback_data="reset")]
        ])
    elif pdf_count >= 1 and batch_mode:
        buttons.extend([
            [InlineKeyboardButton("📋 View Order & Reorder", callback_data="view_order")],
            [InlineKeyboardButton("✅ Done - Merge All", callback_data="merge_pdfs")],
            [InlineKeyboardButton(f"📊 Current: {pdf_count} PDFs", callback_data="show_status")],
            [InlineKeyboardButton("🔄 Cancel & Restart", callback_data="reset")]
        ])
    elif pdf_count == 1:
        buttons.extend([
            [InlineKeyboardButton("➕ Add Another PDF", callback_data="add_pdf")],
            [InlineKeyboardButton("✂️ Remove Pages", callback_data="remove_page")],
            [InlineKeyboardButton("📥 Download PDF", callback_data="finish")]
        ])
    elif pdf_count > 1:
        buttons.extend([
            [InlineKeyboardButton("📋 View Order & Reorder", callback_data="view_order")],
            [InlineKeyboardButton("➕ Add More PDFs", callback_data="add_pdf")],
            [InlineKeyboardButton("🔗 Merge All PDFs", callback_data="merge_pdfs")],
            [InlineKeyboardButton("🔄 Reset All", callback_data="reset")]
        ])
    else:
        buttons.append([InlineKeyboardButton("➕ Add PDF", callback_data="add_pdf")])
    
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def create_reorder_menu(session: UserSession, page: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    items_per_page = 5
    start = page * items_per_page
    end = min(start + items_per_page, len(session.pdfs))
    
    for i in range(start, end):
        pdf = session.pdfs[i]
        btn_text = f"{i+1}. {pdf.filename[:20]}... ({pdf.pages}p)"
        buttons.append([
            InlineKeyboardButton("⬆️", callback_data=f"move_up_{i}"),
            InlineKeyboardButton(btn_text, callback_data=f"info_{i}"),
            InlineKeyboardButton("⬇️", callback_data=f"move_down_{i}")
        ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    if end < len(session.pdfs):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([
        InlineKeyboardButton("🔤 Sort by Name", callback_data="sort_name"),
        InlineKeyboardButton("📄 Sort by Pages", callback_data="sort_pages")
    ])
    
    buttons.append([
        InlineKeyboardButton("✅ Done Reordering", callback_data="done_reorder"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_reorder")
    ])
    
    return InlineKeyboardMarkup(buttons)


def remove_page_from_pdf(input_path: str, output_path: str, page_num: int) -> bool:
    try:
        doc = fitz.open(input_path)
        doc.delete_page(page_num - 1)
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()
        return True
    except Exception as e:
        logger.error(f"Error removing page: {e}")
        return False


def merge_pdfs(pdf_paths: list[str], output_path: str) -> bool:
    try:
        result_pdf = fitz.open()
        
        for pdf_path in pdf_paths:
            with fitz.open(pdf_path) as pdf:
                result_pdf.insert_pdf(pdf)
        
        result_pdf.save(output_path, garbage=4, deflate=True)
        result_pdf.close()
        return True
    except Exception as e:
        logger.error(f"Error merging PDFs: {e}")
        return False


def get_pdf_page_count(pdf_path: str) -> Optional[int]:
    try:
        doc = fitz.open(pdf_path)
        page_count = doc.page_count
        doc.close()
        return page_count
    except Exception as e:
        logger.error(f"Error reading PDF: {e}")
        return None


def get_pdf_size_mb(pdf_path: str) -> float:
    try:
        return round(os.path.getsize(pdf_path) / (1024 * 1024), 2)
    except:
        return 0.0


app = Client(
    "pdf_merger_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    session = get_session(message.from_user.id)
    session.clear()
    session.state = "waiting_pdf"
    
    await message.reply_text(
        "🤖 **Welcome to PDF Merger Bot!**\n\n"
        "📄 **Batch Upload + Reorder!**\n"
        "Send 10-15 PDFs at once and reorder them!\n\n"
        "**How to use:**\n"
        "1️⃣ Send multiple PDF files\n"
        "2️⃣ Click 'View Order & Reorder' to arrange them\n"
        "3️⃣ Click 'Done - Merge All'\n"
        "4️⃣ Get your perfectly ordered merged PDF!\n\n"
        "**Features:**\n"
        "• ⚡ Fast batch merging (PyMuPDF)\n"
        "• 📦 Handle 10-15 PDFs at once\n"
        "• 🔄 Reorder PDFs before merging\n"
        "• 🔤 Auto-sort by name or pages\n"
        "• ✂️ Remove specific pages\n\n"
        "Use /cancel to stop at any time."
    )


@app.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    session = get_session(message.from_user.id)
    session.clear()
    
    await message.reply_text(
        "❌ Operation cancelled.\n"
        "Use /start to begin again."
    )


@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    await message.reply_text(
        "📚 **How to Use:**\n\n"
        "**Batch Upload + Reorder:**\n"
        "1️⃣ Send 10-15 PDF files\n"
        "2️⃣ Click 'View Order & Reorder'\n"
        "3️⃣ Use ⬆️⬇️ buttons to reorder\n"
        "4️⃣ Or use 'Sort by Name/Pages'\n"
        "5️⃣ Click 'Done - Merge All'\n"
        "6️⃣ Download your merged PDF!\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/cancel - Cancel operation\n"
        "/help - Show this message"
    )


@app.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    session = get_session(message.from_user.id)
    
    if session.state not in ["waiting_pdf", "idle", "has_pdfs"]:
        return
    
    if message.document.mime_type != "application/pdf":
        await message.reply_text("❗ Please send a valid PDF document.")
        return
    
    if message.document.file_size > MAX_FILE_SIZE:
        await message.reply_text(
            f"❗ File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB."
        )
        return
    
    if not session.batch_mode:
        session.batch_mode = True
    
    status_msg = await message.reply_text(
        f"⏳ Downloading PDF {len(session.pdfs) + 1}..."
    )
    
    try:
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(
            temp_dir,
            f"pdf_{message.from_user.id}_{len(session.pdfs)}_{message.id}.pdf"
        )
        
        await message.download(file_path)
        
        page_count = get_pdf_page_count(file_path)
        if page_count is None:
            await status_msg.edit_text("❗ Invalid or corrupted PDF file.")
            os.remove(file_path)
            return
        
        file_size = get_pdf_size_mb(file_path)
        filename = message.document.file_name or f"document_{len(session.pdfs)+1}.pdf"
        
        pdf_info = PDFInfo(
            path=file_path,
            filename=filename,
            pages=page_count,
            size=file_size,
            order=len(session.pdfs)
        )
        
        session.add_pdf(pdf_info)
        session.state = "has_pdfs"
        
        total_pages = sum(pdf.pages for pdf in session.pdfs)
        total_size = sum(pdf.size for pdf in session.pdfs)
        
        await status_msg.edit_text(
            f"✅ **PDF {len(session.pdfs)} Added!**\n\n"
            f"📄 {filename[:30]}...\n"
            f"📑 Pages: {page_count} | Size: {file_size} MB\n\n"
            f"📊 **Total: {len(session.pdfs)} PDFs**\n"
            f"📚 Total Pages: {total_pages}\n"
            f"💾 Total Size: {round(total_size, 2)} MB\n\n"
            f"{'📤 Send more or reorder!' if len(session.pdfs) < 15 else '⚠️ Max 15 PDFs!'}",
            reply_markup=create_main_menu(len(session.pdfs), session.is_merged, session.batch_mode)
        )
    
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await status_msg.edit_text("❗ Error processing PDF. Please try again.")


@app.on_callback_query()
async def handle_callback(client: Client, callback: CallbackQuery):
    session = get_session(callback.from_user.id)
    action = callback.data
    
    try:
        if action == "add_pdf":
            await callback.answer()
            session.state = "waiting_pdf"
            session.batch_mode = True
            await callback.message.edit_text(
                f"📄 Send PDF files!\n\nCurrent: {len(session.pdfs)} PDFs",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data="cancel")
                ]])
            )
        
        elif action == "view_order":
            if not session.pdfs:
                await callback.answer("No PDFs to reorder!", show_alert=True)
                return
            
            await callback.answer()
            session.state = "reordering"
            session.temp_data['reorder_page'] = 0
            
            order_text = "📋 **Current PDF Order:**\n\n"
            for i, pdf in enumerate(session.pdfs, 1):
                order_text += f"{i}. {pdf.filename[:35]}...\n"
                order_text += f"   📄 {pdf.pages} pages | 💾 {pdf.size} MB\n\n"
            
            order_text += "Use ⬆️⬇️ to reorder:"
            
            await callback.message.edit_text(
                order_text,
                reply_markup=create_reorder_menu(session, 0)
            )
        
        elif action.startswith("move_up_"):
            idx = int(action.split("_")[2])
            if idx > 0:
                session.move_pdf(idx, idx - 1)
                page = session.temp_data.get('reorder_page', 0)
                
                order_text = "📋 **Current PDF Order:**\n\n"
                for i, pdf in enumerate(session.pdfs, 1):
                    order_text += f"{i}. {pdf.filename[:35]}...\n"
                    order_text += f"   📄 {pdf.pages} pages | 💾 {pdf.size} MB\n\n"
                
                await callback.message.edit_text(
                    order_text,
                    reply_markup=create_reorder_menu(session, page)
                )
            await callback.answer("Moved up!")
        
        elif action.startswith("move_down_"):
            idx = int(action.split("_")[2])
            if idx < len(session.pdfs) - 1:
                session.move_pdf(idx, idx + 1)
                page = session.temp_data.get('reorder_page', 0)
                
                order_text = "📋 **Current PDF Order:**\n\n"
                for i, pdf in enumerate(session.pdfs, 1):
                    order_text += f"{i}. {pdf.filename[:35]}...\n"
                    order_text += f"   📄 {pdf.pages} pages | 💾 {pdf.size} MB\n\n"
                
                await callback.message.edit_text(
                    order_text,
                    reply_markup=create_reorder_menu(session, page)
                )
            await callback.answer("Moved down!")
        
        elif action.startswith("info_"):
            idx = int(action.split("_")[1])
            pdf = session.pdfs[idx]
            await callback.answer(
                f"📄 {pdf.filename}\n📑 Pages: {pdf.pages}\n💾 Size: {pdf.size} MB",
                show_alert=True
            )
        
        elif action == "sort_name":
            session.pdfs.sort(key=lambda x: x.filename.lower())
            await callback.answer("Sorted by name!")
            
            order_text = "📋 **PDFs Sorted by Name:**\n\n"
            for i, pdf in enumerate(session.pdfs, 1):
                order_text += f"{i}. {pdf.filename[:35]}...\n"
            
            await callback.message.edit_text(
                order_text,
                reply_markup=create_reorder_menu(session, 0)
            )
        
        elif action == "sort_pages":
            session.pdfs.sort(key=lambda x: x.pages)
            await callback.answer("Sorted by pages!")
            
            order_text = "📋 **PDFs Sorted by Pages:**\n\n"
            for i, pdf in enumerate(session.pdfs, 1):
                order_text += f"{i}. {pdf.filename[:35]}... ({pdf.pages}p)\n"
            
            await callback.message.edit_text(
                order_text,
                reply_markup=create_reorder_menu(session, 0)
            )
        
        elif action == "done_reorder":
            await callback.answer("Order saved!")
            session.state = "has_pdfs"
            
            await callback.message.edit_text(
                f"✅ **PDF Order Confirmed!**\n\n"
                f"📊 Total: {len(session.pdfs)} PDFs\n\n"
                "Ready to merge!",
                reply_markup=create_main_menu(len(session.pdfs), session.is_merged, session.batch_mode)
            )
        
        elif action == "cancel_reorder":
            await callback.answer()
            session.state = "has_pdfs"
            await callback.message.edit_text(
                f"📊 Current: {len(session.pdfs)} PDFs",
                reply_markup=create_main_menu(len(session.pdfs), session.is_merged, session.batch_mode)
            )
        
        elif action == "merge_pdfs":
            if len(session.pdfs) < 2:
                await callback.answer("Need at least 2 PDFs!", show_alert=True)
                return
            
            await callback.answer("Merging...")
            total_pdfs = len(session.pdfs)
            total_pages = sum(pdf.pages for pdf in session.pdfs)
            
            await callback.message.edit_text(
                f"🔄 **Merging {total_pdfs} PDFs...**\n📑 Total Pages: {total_pages}"
            )
            
            output_path = os.path.join(
                tempfile.gettempdir(),
                f"merged_{callback.from_user.id}.pdf"
            )
            
            pdf_paths = [pdf.path for pdf in session.pdfs]
            
            if merge_pdfs(pdf_paths, output_path):
                for pdf in session.pdfs:
                    try:
                        os.remove(pdf.path)
                    except:
                        pass
                
                page_count = get_pdf_page_count(output_path)
                file_size = get_pdf_size_mb(output_path)
                
                merged_pdf = PDFInfo(
                    path=output_path,
                    filename="merged_document.pdf",
                    pages=page_count,
                    size=file_size,
                    order=0
                )
                
                session.pdfs = [merged_pdf]
                session.is_merged = True
                session.batch_mode = False
                
                await callback.message.edit_text(
                    f"✅ **Merged {total_pdfs} PDFs!**\n\n"
                    f"📄 Pages: {page_count}\n💾 Size: {file_size} MB",
                    reply_markup=create_main_menu(1, is_merged=True)
                )
            else:
                await callback.message.edit_text("❗ Error merging PDFs")
        
        elif action == "finish":
            if not session.pdfs:
                await callback.answer("No PDF!", show_alert=True)
                return
            
            await callback.answer("Preparing...")
            await callback.message.edit_text("📤 Preparing your PDF...")
            
            try:
                pdf_info = session.pdfs[0]
                
                await client.send_document(
                    chat_id=callback.message.chat.id,
                    document=pdf_info.path,
                    caption="✅ Here's your PDF!",
                    file_name=pdf_info.filename
                )
                
                session.clear()
                await callback.message.edit_text("✅ Done! Use /start for more.")
            except Exception as e:
                logger.error(f"Error sending: {e}")
                await callback.message.edit_text("❗ Error sending PDF")
        
        elif action == "reset":
            await callback.answer("Resetting...")
            session.clear()
            session.state = "waiting_pdf"
            await callback.message.edit_text("🔄 Reset! Send PDFs to start over.")
        
        elif action == "cancel":
            await callback.answer("Cancelled")
            session.clear()
            await callback.message.edit_text("❌ Cancelled. Use /start to begin.")
    
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await callback.answer("Error occurred", show_alert=True)


@app.on_message(filters.text)
async def handle_text(client: Client, message: Message):
    session = get_session(message.from_user.id)
    
    if session.state != "waiting_page_number":
        return
    
    if not message.text.isdigit():
        await message.reply_text("❗ Please enter a valid number.")
        return
    
    page_num = int(message.text)
    page_count = session.temp_data.get('page_count', 0)
    
    if page_num < 1 or page_num > page_count:
        await message.reply_text(f"❗ Enter 1-{page_count}")
        return
    
    status_msg = await message.reply_text("✂️ Removing page...")
    
    try:
        pdf_idx = len(session.pdfs) - 1
        pdf_info = session.pdfs[pdf_idx]
        output_path = os.path.join(
            tempfile.gettempdir(),
            f"modified_{message.from_user.id}_{pdf_idx}.pdf"
        )
        
        if remove_page_from_pdf(pdf_info.path, output_path, page_num):
            os.remove(pdf_info.path)
            
            new_pages = get_pdf_page_count(output_path)
            new_size = get_pdf_size_mb(output_path)
            
            session.pdfs[pdf_idx] = PDFInfo(
                path=output_path,
                filename=pdf_info.filename,
                pages=new_pages,
                size=new_size,
                order=pdf_info.order
            )
            session.state = "has_pdfs"
            
            await status_msg.edit_text(
                f"✅ **Page {page_num} Removed!**\n\n"
                f"📄 Pages: {new_pages}\n💾 Size: {new_size} MB",
                reply_markup=create_main_menu(len(session.pdfs), session.is_merged)
            )
        else:
            await status_msg.edit_text("❗ Error removing page")
    
    except Exception as e:
        logger.error(f"Page removal error: {e}")
        await status_msg.edit_text("❗ Error occurred")


def start_bot():
    """Start the Telegram bot in background"""
    print("🚀 Starting Telegram bot...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(app.run())

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 PDF Merger Bot - Render.com Edition")
    print("=" * 50)
    print("⚡ Running with Flask web server")
    print("=" * 50)
    
    # Start Pyrogram bot in background thread
    bot_thread = Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    print("✅ Bot started in background")
    print("🌐 Starting Flask server...")
    
    # Start Flask (this blocks)
    run_flask()
else:
    # When run via gunicorn, start bot in background
    bot_thread = Thread(target=start_bot, daemon=True)
    bot_thread.start()
