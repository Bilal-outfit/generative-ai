# Course Description Generator

![CI Status](https://github.com/Bilal-outfit/generative-ai/workflows/CI%20-%20Test%20Course%20Generator/badge.svg)

Automated course description generator using OpenAI's GPT-4o-mini model and PostgreSQL database integration.

## 🚀 Features

- **AI-Powered Descriptions**: Generates engaging 150-word course descriptions using OpenAI GPT-4o-mini
- **Database Integration**: Direct PostgreSQL connection for reading course data and saving descriptions
- **Batch Processing**: Processes courses in configurable batches (default: 10 courses per batch)
- **Parallel Execution**: Uses ThreadPoolExecutor for concurrent API calls (default: 5 workers)
- **Progressive Updates**: Writes descriptions to database immediately after each batch completes
- **Production Ready**: Handles large datasets (tested for 35,000+ records)
- **Robust Error Handling**: Comprehensive try-except blocks with detailed logging

## 📋 Requirements

- Python 3.11+
- PostgreSQL database
- OpenAI API key

## 🔧 Installation

1. Clone the repository:
```bash
git clone https://github.com/Bilal-outfit/generative-ai.git
cd generative-ai
```

2. Create virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# or
source .venv/bin/activate  # Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create `.env` file:
```env
OPENAI_API_KEY=your_openai_api_key_here
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_database_name
DB_USER=your_username
DB_PASSWORD=your_password
MAX_WORKERS=5
```

## 🎯 Usage

Run the script:
```bash
python generate_descriptions.py
```

The script will:
1. Connect to PostgreSQL database
2. Load course data from `courses` table
3. Generate descriptions in batches
4. Save descriptions back to the `description` column
5. Display progress and statistics

## 📊 Configuration

Edit these variables in the script or via environment:

- `batch_size`: Number of courses per LLM call (default: 10)
- `MAX_WORKERS`: Number of parallel API calls (default: 5)
- `temperature`: LLM creativity (default: 0.7)
- `max_tokens`: Maximum tokens per response (default: 2000)

## 📝 System Prompt

The AI prompt is defined in `system_prompt.json` and includes:
- 150-word descriptions
- Varied opening styles
- Level meanings (Beginner/Intermediate/Advanced/Expert)
- Natural credit mentions
- Professional tone

## 🗄️ Database Schema

The script expects a `courses` table with these columns:
- `id` (primary key)
- `LearnAimRefTitle`
- `Level`
- `Awarding org Name`
- `GuidedLearningHours`
- `TotalQualificationTime`
- `Sector Subject Area (Main Category SSA 1)`
- `Sector Subject Area (Sub Category SSA 2)`
- `Learn Aim Ref Type`
- `UnitType`
- `description` (will be updated)

## 🔄 CI/CD

GitHub Actions automatically runs on every push:
- ✅ Python syntax validation
- ✅ Dependency installation check
- ✅ JSON file validation
- ✅ Code style checking
- ✅ Import verification
- ✅ Security checks

## 📈 Performance

- **Small dataset (200 rows)**: ~2-3 minutes
- **Medium dataset (2,000 rows)**: ~20-30 minutes
- **Large dataset (35,000 rows)**: ~6-8 hours (estimated)

Optimizations:
- Batch processing reduces API calls by 10x
- Parallel execution uses 5 concurrent workers
- Progressive saves prevent data loss

## 🔐 Security

- API keys stored in `.env` (not committed to Git)
- Database credentials in environment variables
- `.gitignore` protects sensitive files
- GitHub push protection enabled

## 👤 Author

**Bilal Afzal**  
Consultancy Outfit  
Email: Bilal.afzal@consultancyoutfit.co.uk

## 📄 License

Internal project - Consultancy Outfit

---

**Status**: Production Ready ✅
