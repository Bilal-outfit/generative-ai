import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        return conn
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}", file=sys.stderr)
        return None


def load_courses_from_db():
    """
    Load all individual course records from database.
    Returns a list of dictionaries, one for each row.
    """
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    id,
                    "LearnAimRefTitle" as course_name,
                    "Category Title" as category_title,
                    "Level",
                    "Awarding org Name" as awarding_org,
                    "GuidedLearningHours" as guided_hours,
                    "TotalQualificationTime" as total_time,
                    "Sector Subject Area (Main Category SSA 1)" as main_sector,
                    "Sector Subject Area (Sub Category SSA 2)" as sub_sector,
                    "Learn Aim Ref Type" as course_type,
                    "UnitType" as unit_type
                FROM courses
                WHERE "LearnAimRefTitle" IS NOT NULL
                ORDER BY id
            """)
            
            rows = cur.fetchall()
            return [dict(row) for row in rows]
            
    except Exception as e:
        print(f"ERROR: Failed to load courses from database: {e}", file=sys.stderr)
        return []
    finally:
        conn.close()


def save_descriptions_to_db(output_data):
    """
    Save generated descriptions back to database by row ID.
    output_data: {row_id: {"description": "..."}}
    """
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            for row_id, desc_data in output_data.items():
                description = desc_data.get("description", "")
                if description and not description.startswith("[ERROR"):
                    cur.execute("""
                        UPDATE courses 
                        SET description = %s 
                        WHERE id = %s
                    """, (description, int(row_id)))
            
            conn.commit()
            return True
    except Exception as e:
        print(f"ERROR: Failed to save descriptions to database: {e}", file=sys.stderr)
        conn.rollback()
        return False
    finally:
        conn.close()


def load_system_prompt(path="system_prompt.json"):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg.get("prompt", "")


def validate_json(text):
    try:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return True, "", json.loads(cleaned.strip())
    except Exception as e:
        return False, str(e), {}


def generate_batch_descriptions(system_prompt, batch_courses, batch_ids, batch_num, total_batches):
    client = OpenAI()
    
    user_prompt = "Generate descriptions for the following courses:\n\n"
    for i, info in enumerate(batch_courses, 1):
        user_prompt += f"{i}. {info}\n"
    
    print(f"  Processing batch {batch_num}/{total_batches} ({len(batch_ids)} courses)...")
    start_time = time.time()
    
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=1500
        )
        
        response_text = completion.choices[0].message.content.strip()
        is_valid, error_msg, descriptions = validate_json(response_text)
        
        if not is_valid:
            print(f"    ERROR: {error_msg}", file=sys.stderr)
            return {row_id: {"description": f"[ERROR: {error_msg}]"} for row_id in batch_ids}
        
        elapsed_time = time.time() - start_time
        print(f"    ✓ Batch {batch_num} completed in {elapsed_time:.2f} seconds")
        
        output = {}
        for idx, row_id in enumerate(batch_ids):
            key = f"Course {idx + 1}"
            if key in descriptions:
                desc_data = descriptions[key]
                if isinstance(desc_data, dict) and "description" in desc_data:
                    output[row_id] = desc_data
                else:
                    output[row_id] = {"description": str(desc_data.get("description", "") if isinstance(desc_data, dict) else desc_data)}
            else:
                output[row_id] = {"description": "[ERROR: Description not found]"}
        
        return output
        
    except Exception as e:
        print(f"    ERROR: Batch {batch_num} failed: {e}", file=sys.stderr)
        return {row_id: {"description": f"[ERROR: {e}]"} for row_id in batch_ids}


def generate_all_descriptions(data):
    system_prompt = load_system_prompt()
    
    if not data:
        return {}
    
    courses_info = []
    course_ids = []
    
    for row in data:
        row_id = row.get('id')
        course_name = row.get('course_name', 'Unknown')
        level = row.get('Level', '')
        course_type = row.get('course_type', '')
        guided_hours = row.get('guided_hours', 0)
        total_time = row.get('total_time', 0)
        main_sector = row.get('main_sector', '')
        sub_sector = row.get('sub_sector', '')
        awarding_org = row.get('awarding_org', '')
        
        # Build info string for this row
        info = course_name
        if level:
            info += f" | Level: {level}"
        if course_type:
            info += f" | Type: {course_type}"
        if guided_hours and guided_hours != 0:
            info += f" | Guided Learning Hours: {guided_hours}"
        if total_time and total_time != 0:
            info += f" | Total Qualification Time: {total_time}"
        if main_sector:
            info += f" | Sector: {main_sector}"
        if sub_sector:
            info += f" | Sub-Sector: {sub_sector}"
        if awarding_org:
            info += f" | Awarding Org: {awarding_org}"
        
        courses_info.append(info)
        course_ids.append(str(row_id))
    
    batch_size = 10
    total_batches = (len(course_ids) + batch_size - 1) // batch_size
    max_workers = int(os.getenv("MAX_WORKERS", "5"))
    
    print(f"Processing {len(course_ids)} courses in {total_batches} batches of {batch_size}...")
    
    completed = 0
    total_saved = 0
    
    for group_start in range(0, total_batches, max_workers):
        group_end = min(group_start + max_workers, total_batches)
        print(f"  Processing batches {group_start + 1}-{group_end}...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {}
            for batch_idx in range(group_start, group_end):
                start_idx = batch_idx * batch_size
                end_idx = min(start_idx + batch_size, len(course_ids))
                
                future = executor.submit(
                    generate_batch_descriptions,
                    system_prompt, courses_info[start_idx:end_idx], course_ids[start_idx:end_idx],
                    batch_idx + 1, total_batches
                )
                future_to_batch[future] = batch_idx + 1
            
            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future]
                batch_output = future.result()
                
                # Save to database immediately after batch completes
                if save_descriptions_to_db(batch_output):
                    total_saved += len(batch_output)
                    print(f"    ✓ Batch {batch_num} saved to database ({total_saved}/{len(course_ids)} total)")
                else:
                    print(f"    ✗ Batch {batch_num} failed to save to database", file=sys.stderr)
                
                completed += 1
        
        print(f"  ✓ Completed batches {group_start + 1}-{group_end}")
    
    print(f"✓ Completed processing and saved all {total_saved} courses")
    return True




def main():
    load_dotenv()

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. Put it in a .env file.", file=sys.stderr)
        return

    if not all([os.getenv("DB_HOST"), os.getenv("DB_NAME"), os.getenv("DB_USER"), os.getenv("DB_PASSWORD")]):
        print("ERROR: Database connection details not set in .env file.", file=sys.stderr)
        print("Please set DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD in your .env file.", file=sys.stderr)
        return

    print("Loading courses from database...")
    data = load_courses_from_db()
    if not data:
        print("ERROR: No courses found in database or connection failed.", file=sys.stderr)
        return

    print(f"Found {len(data)} courses in database")
    generate_all_descriptions(data)


if __name__ == "__main__":
    main()

