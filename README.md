# 📄 PDF Merger Telegram Bot

A fast and efficient Telegram bot for merging PDFs, removing pages, and managing PDF documents - built with Pyrogram and PyMuPDF.

## ✨ Features

- ⚡ **Lightning Fast** - Uses PyMuPDF (5-10x faster than PyPDF2)
- 🔗 **Merge Multiple PDFs** - Combine unlimited PDF files into one
- ✂️ **Remove Pages** - Delete specific pages from any PDF
- 💾 **Smart File Management** - Automatic cleanup of temporary files
- 🎯 **User-Friendly Interface** - Interactive buttons and clear instructions
- 📊 **Real-time Info** - Shows page count and file size
- 🔒 **Session-Based** - Isolated user sessions for privacy

## 🚀 Quick Start

### Prerequisites
```bash
pip install pyrofork tgcrypto PyMuPDF
```

### Setup

1. Get your Telegram API credentials:
   - **API_ID** and **API_HASH** from [my.telegram.org](https://my.telegram.org)
   - **BOT_TOKEN** from [@BotFather](https://t.me/BotFather)

2. Edit the configuration:
```python
API_ID = "YOUR_API_ID"
API_HASH = "YOUR_API_HASH"
BOT_TOKEN = "YOUR_BOT_TOKEN"
```

3. Run the bot:
```bash
python main.py
```

## 📖 Usage

1. Start the bot with `/start`
2. Send a PDF file
3. Choose your operation:
   - Add more PDFs
   - Remove specific pages
   - Merge all PDFs
   - Download the result

## 🛠️ Commands

- `/start` - Initialize the bot
- `/cancel` - Cancel current operation
- `/help` - Show help message

## 📋 Configuration
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB (adjustable)
```

## 🔧 Tech Stack

- **[Pyrogram](https://github.com/pyrogram/pyrogram)** - Modern Telegram Bot API framework
- **[PyMuPDF](https://github.com/pymupdf/PyMuPDF)** - High-performance PDF library
- **Python 3.8+**

## 📊 Performance

| Operation | Time |
|-----------|------|
| Merge 50MB PDF | ~2-3 seconds |
| Remove Page | ~1 second |
| Process 100+ pages | < 5 seconds |


## 📝 License

MIT License - feel free to use and modify!

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

## ⭐ Support

If you found this helpful, give it a star! ⭐

---

Made with ❤️ using Pyrogram and PyMuPDF
