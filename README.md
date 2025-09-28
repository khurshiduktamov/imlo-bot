# Imlo Bot - Uzbek Spell Checker

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.x-blue.svg)
![Status](https://img.shields.io/badge/status-active-green.svg)

**Imlo Bot** is a comprehensive spell checking tool designed specifically for the Uzbek language. This project aims to help users identify and correct spelling errors in Uzbek text, supporting both Latin and Cyrillic scripts commonly used in Uzbekistan.

## 🚀 Features

- **Uzbek Language Support**: Native spell checking for Uzbek language
- **Multi-Script Support**: Works with both Latin and Cyrillic Uzbek scripts
- **Error Detection**: Identifies common spelling mistakes and typos
- **Word Suggestions**: Provides correction suggestions for misspelled words
- **Bot Interface**: Easy-to-use bot interface for quick spell checking
- **Fast Processing**: Optimized for quick text analysis

## 📋 Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Examples](#examples)
- [Configuration](#configuration)
- [Contributing](#contributing)
- [License](#license)
- [Support](#support)

## 🛠 Installation

### Prerequisites

- Python 3.x
- pip package manager

### Quick Install

```bash
# Clone the repository
git clone https://github.com/khurshiduktamov/imlo-bot.git

# Navigate to project directory
cd imlo-bot

# Install required dependencies
pip install -r requirements.txt
```

### Development Setup

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 🎯 Usage

### Basic Usage

```python
from imlo_bot import ImloChecker

# Initialize the spell checker
checker = ImloChecker()

# Check spelling in a text
text = "Bugun havo juda chiroyli"
result = checker.check_spelling(text)

# Get suggestions for corrections
suggestions = checker.get_suggestions("xato_soz")
```

### Command Line Interface

```bash
# Check a single sentence
python imlo_bot.py "Salom dunyo!"

# Check text from file
python imlo_bot.py --file input.txt

# Get help
python imlo_bot.py --help
```

### Bot Interface

```python
# Start the bot
python bot.py

# The bot will be ready to receive text for spell checking
```

## 📝 Examples

### Example 1: Basic Spell Checking

```python
from imlo_bot import ImloChecker

checker = ImloChecker()

# Text with potential errors
text = "Men bugun maktabga bordim va o'qituvchi bilan gaplashdim"

# Check spelling
results = checker.check_spelling(text)

for error in results['errors']:
    print(f"Error: {error['word']}")
    print(f"Suggestions: {error['suggestions']}")
```

### Example 2: Batch Processing

```python
# Process multiple texts
texts = [
    "Birinchi matn",
    "Ikkinchi matn",
    "Uchinchi matn"
]

for i, text in enumerate(texts):
    result = checker.check_spelling(text)
    print(f"Text {i+1}: {result['corrected_count']} corrections made")
```

## ⚙️ Configuration

Create a `config.json` file to customize the spell checker:

```json
{
    "language": "uz",
    "script": "latin",
    "dictionary_path": "./dictionaries/",
    "min_word_length": 2,
    "max_suggestions": 5,
    "case_sensitive": false
}
```

### Configuration Options

- `language`: Target language (default: "uz")
- `script`: Script type - "latin" or "cyrillic" (default: "latin")
- `dictionary_path`: Path to dictionary files
- `min_word_length`: Minimum word length to check
- `max_suggestions`: Maximum number of suggestions per error
- `case_sensitive`: Whether to perform case-sensitive checking

## 🗃️ Dictionary

The spell checker uses comprehensive Uzbek dictionaries containing:

- **Common Words**: Frequently used Uzbek words
- **Technical Terms**: Scientific and technical vocabulary
- **Proper Nouns**: Names, places, and organizations
- **Regional Variants**: Different regional spellings and dialects

### Adding Custom Words

```python
# Add custom words to dictionary
checker.add_word("yangi_soz")

# Add multiple words
checker.add_words(["soz1", "soz2", "soz3"])

# Save custom dictionary
checker.save_custom_dictionary()
```

## 🤝 Contributing

We welcome contributions to improve the Uzbek spell checker! Here's how you can help:

### Ways to Contribute

1. **Report Bugs**: Submit issues for any bugs you find
2. **Suggest Features**: Propose new features or improvements
3. **Improve Dictionary**: Add missing words or correct existing ones
4. **Code Contributions**: Submit pull requests with improvements
5. **Documentation**: Help improve documentation and examples

### Development Guidelines

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Write or update tests
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code Style

- Follow PEP 8 for Python code
- Add docstrings to all functions
- Include type hints where appropriate
- Write unit tests for new features

## 🧪 Testing

Run the test suite to ensure everything works correctly:

```bash
# Run all tests
python -m pytest

# Run specific test file
python -m pytest tests/test_spell_checker.py

# Run with coverage
python -m pytest --cov=imlo_bot
```

## 📊 Performance

The spell checker is optimized for performance:

- **Speed**: Processes 1000+ words per second
- **Memory**: Efficient dictionary loading and caching
- **Accuracy**: High precision with minimal false positives

## 🌍 Language Support

Currently supports:

- **Uzbek (Latin)**: Modern Uzbek using Latin alphabet
- **Uzbek (Cyrillic)**: Traditional Uzbek using Cyrillic script


## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Uzbek language experts and linguists
- Open source spell checking libraries
- Contributors to Uzbek digital resources
- The Uzbek developer community

## 📞 Support

If you need help or have questions:

- **Issues**: [GitHub Issues](https://github.com/khurshiduktamov/imlo-bot/issues)
- **Email**: khurshid.uktamov@gmail.com
- **Discussions**: Use GitHub Discussions for general questions

## 🔄 Changelog

### Version 1.0.0
- Initial release
- Basic spell checking functionality
- Support for Latin Uzbek
- Command line interface

### Version 0.9.0
- Beta release
- Core spell checking engine
- Dictionary implementation

---

**Made with ❤️ for the Uzbek language community**

*If this project helped you, please consider giving it a star ⭐*
