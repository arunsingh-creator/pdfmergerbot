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

# ============= CONFIGURATION =============
API_ID = os.getenv("API_ID", "YOUR_API_ID")
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
if API_ID == "YOUR_API_ID" or API_HASH == "YOUR_API_HASH" or BOT_TOKEN == "YOUR_BOT_TOKEN":
    raise ValueError("Please set API_ID, API_HASH, and BOT_TOKEN environment variables!")


# ============= LOGGING SETUP =============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


user_sessions = {}
class UserSession:
    """Manages user's PDF editing session"""
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.pdfs = []
        self.state = "idle"
        self.temp_data = {}
    
    def add_pdf(self, path: str):
        self.pdfs.append(path)
    
    def clear(self):
        """Clean up all temporary files"""
        for pdf_path in self.pdfs:
            try:
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
            except Exception as e:
                logger.error(f"Failed to remove {pdf_path}: {e}")
        self.pdfs.clear()
        self.temp_data.clear()
        self.state = "idle"


def get_session(user_id: int) -> UserSession:
    """Get or create user session"""
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]

def create_main_menu(pdf_count: int) -> InlineKeyboardMarkup:
    """Create dynamic menu based on PDF count"""
    buttons = [[InlineKeyboardButton("➕ Add Another PDF", callback_data="add_pdf")]]
    
    if pdf_count == 1:
        buttons.extend([
            [InlineKeyboardButton("✂️ Remove a PDF", callback_data="remove_page")],
            [InlineKeyboardButton("✅ Finish & Download", callback_data="finish")]
        ])
    elif pdf_count > 1:
        buttons.extend([
            [InlineKeyboardButton("✂️ Remove PDF (Last PDF)", callback_data="remove_page")],
            [InlineKeyboardButton("🔗 Merge All PDFs", callback_data="merge_pdfs")],
            [InlineKeyboardButton("🔄 Reset All", callback_data="reset")]
        ])
    
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def remove_page_from_pdf(input_path: str, output_path: str, page_num: int) -> bool:
    """Remove a specific page from PDF"""
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
    """Merge multiple PDFs into one - FAST with PyMuPDF"""
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
    """Get the number of pages in a PDF"""
    try:
        doc = fitz.open(pdf_path)
        page_count = doc.page_count
        doc.close()
        return page_count
    except Exception as e:
        logger.error(f"Error reading PDF: {e}")
        return None


def get_pdf_size_mb(pdf_path: str) -> float:
    """Get PDF file size in MB"""
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
    """Handle /start command"""
    session = get_session(message.from_user.id)
    session.clear()
    session.state = "waiting_pdf"
    
    await message.reply_text(
        "🤖 **Welcome to PDF Merger Bot!**\n\n"
        "📄 Send me a PDF file to get started.\n\n"
        "**Features:**\n"
        "• ⚡ Fast PDF merging (PyMuPDF)\n"
        "• ✂️ Remove specific pages\n"
        "• 📦 Merge multiple PDFs\n"
        "• 🎯 Easy-to-use interface\n\n"
        "Use /cancel to stop at any time."
    )


@app.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    """Handle /cancel command"""
    session = get_session(message.from_user.id)
    session.clear()
    
    await message.reply_text(
        "❌ Operation cancelled.\n"
        "Use /start to begin again."
    )


@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    await message.reply_text(
        "📚 **How to Use:**\n\n"
        "1️⃣ Send a PDF file\n"
        "2️⃣ Choose an option:\n"
        "   • Add more PDFs\n"
        "   • Remove PDF\n"
        "   • Merge PDFs\n"
        "3️⃣ Download your result\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/cancel - Cancel current operation\n"
        "/help - Show this message"
    )

@app.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    """Handle incoming PDF documents"""
    session = get_session(message.from_user.id)
    
    if session.state not in ["waiting_pdf", "idle"]:
        return
    

    if message.document.mime_type != "application/pdf":
        await message.reply_text("❗ Please send a valid PDF document.")
        return
    

    if message.document.file_size > MAX_FILE_SIZE:
        await message.reply_text(
            f"❗ File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB."
        )
        return
    
    status_msg = await message.reply_text("⏳ Downloading PDF...")
    
    try:
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(
            temp_dir,
            f"pdf_{message.from_user.id}_{len(session.pdfs)}.pdf"
        )
        
        await message.download(file_path)
        

        page_count = get_pdf_page_count(file_path)
        if page_count is None:
            await status_msg.edit_text("❗ Invalid or corrupted PDF file.")
            os.remove(file_path)
            return
        
        file_size = get_pdf_size_mb(file_path)
        session.add_pdf(file_path)
        session.state = "has_pdfs"
        
        await status_msg.edit_text(
            f"✅ **PDF Received!**\n\n"
            f"📄 Pages: {page_count}\n"
            f"💾 Size: {file_size} MB\n"
            f"📊 Total PDFs: {len(session.pdfs)}\n\n"
            "Choose an option:",
            reply_markup=create_main_menu(len(session.pdfs))
        )
    
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await status_msg.edit_text("❗ Error processing PDF. Please try again.")

@app.on_callback_query()
async def handle_callback(client: Client, callback: CallbackQuery):
    """Handle button callbacks"""
    session = get_session(callback.from_user.id)
    action = callback.data
    
    if action == "add_pdf":
        session.state = "waiting_pdf"
        await callback.message.edit_text(
            "📄 Send another PDF file:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cancel")
            ]])
        )
    
    elif action == "remove_page":
        if not session.pdfs:
            await callback.answer("No PDFs available!", show_alert=True)
            return
        
        pdf_path = session.pdfs[-1]
        page_count = get_pdf_page_count(pdf_path)
        
        if page_count is None:
            await callback.answer("Error reading PDF!", show_alert=True)
            return
        
        session.state = "waiting_page_number"
        session.temp_data['page_count'] = page_count
        
        await callback.message.edit_text(
            f"✂️ **Remove a Page**\n\n"
            f"PDF has {page_count} pages.\n"
            f"Enter the page number to remove (1-{page_count}):"
        )
    
    elif action == "merge_pdfs":
        if len(session.pdfs) < 2:
            await callback.answer("Need at least 2 PDFs to merge!", show_alert=True)
            return
        
        await callback.message.edit_text("🔄 Merging PDFs... (Fast with PyMuPDF)")
        
        output_path = os.path.join(
            tempfile.gettempdir(),
            f"merged_{callback.from_user.id}.pdf"
        )
        
        if merge_pdfs(session.pdfs, output_path):
            for pdf in session.pdfs:
                os.remove(pdf)
            
            session.pdfs = [output_path]
            page_count = get_pdf_page_count(output_path)
            file_size = get_pdf_size_mb(output_path)
            
            await callback.message.edit_text(
                f"✅ **PDFs Merged Successfully!**\n\n"
                f"📄 Total Pages: {page_count}\n"
                f"💾 Size: {file_size} MB\n\n"
                "Choose an option:",
                reply_markup=create_main_menu(1)
            )
        else:
            await callback.message.edit_text(
                "❗ Error merging PDFs. Please try again.",
                reply_markup=create_main_menu(len(session.pdfs))
            )
    
    elif action == "reset":
        session.clear()
        session.state = "waiting_pdf"
        await callback.message.edit_text(
            "🔄 Reset complete.\n"
            "📄 Send a PDF to start over."
        )
    
    elif action == "finish":
        if not session.pdfs:
            await callback.answer("No PDF available!", show_alert=True)
            return
        
        await callback.message.edit_text("📤 Preparing your PDF...")
        
        try:
            await client.send_document(
                chat_id=callback.message.chat.id,
                document=session.pdfs[0],
                caption="✅ Here's your PDF!"
            )
            
            session.clear()
            await callback.message.edit_text(
                "✅ Done! Use /start to create another PDF."
            )
        except Exception as e:
            logger.error(f"Error sending document: {e}")
            await callback.message.edit_text("❗ Error sending PDF. Please try again.")
    
    elif action == "cancel":
        session.clear()
        await callback.message.edit_text(
            "❌ Operation cancelled.\n"
            "Use /start to begin again."
        )
    
    await callback.answer()
    
@app.on_message(filters.text)
async def handle_text(client: Client, message: Message):
    """Handle text input for page number"""
    session = get_session(message.from_user.id)
    
    if session.state != "waiting_page_number":
        return
    
    if not message.text.isdigit():
        await message.reply_text("❗ Please enter a valid number.")
        return
    
    page_num = int(message.text)
    page_count = session.temp_data.get('page_count', 0)
    
    if page_num < 1 or page_num > page_count:
        await message.reply_text(
            f"❗ Page number out of range.\n"
            f"Enter a number between 1 and {page_count}."
        )
        return
    
    status_msg = await message.reply_text("✂️ Removing page...")
    
    try:
        pdf_idx = len(session.pdfs) - 1
        input_path = session.pdfs[pdf_idx]
        output_path = os.path.join(
            tempfile.gettempdir(),
            f"modified_{message.from_user.id}_{pdf_idx}.pdf"
        )
        
        if remove_page_from_pdf(input_path, output_path, page_num):
            os.remove(input_path)
            session.pdfs[pdf_idx] = output_path
            session.state = "has_pdfs"
            
            new_page_count = get_pdf_page_count(output_path)
            file_size = get_pdf_size_mb(output_path)
            
            await status_msg.edit_text(
                f"✅ **PDF {page_num} Removed!**\n\n"
                f"📄 Pages Remaining: {new_page_count}\n"
                f"💾 Size: {file_size} MB\n\n"
                "Choose an option:",
                reply_markup=create_main_menu(len(session.pdfs))
            )
        else:
            await status_msg.edit_text("❗ Error removing page. Please try again.")
    
    except Exception as e:
        logger.error(f"Error in page removal: {e}")
        await status_msg.edit_text("❗ Error removing page. Please try again.")


# ============= MAIN EXECUTION =============
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 PDF Merger Bot - PyMuPDF Edition")
    print("=" * 50)
    print("⚡ Features: Fast merging, page removal")
    print("📚 Library: PyMuPDF (much faster than PyPDF2)")
    print("=" * 50)
    print("\n🚀 Starting bot...")
    print("⚠️  Press Ctrl+C to stop\n")
    
    app.run()
