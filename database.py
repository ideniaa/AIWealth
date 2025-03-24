import sqlite3
from datetime import datetime
from contextlib import contextmanager
import logging
import decimal
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('finance_db')

# Database configuration
DB_PATH = 'database.db'

# Custom JSON encoder for Decimal type and datetime to help with UI display
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        return super().default(obj)

@contextmanager
def db_connection():
    """Context manager for database connections to ensure proper closing"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize the database with all necessary tables"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            # Create tables with proper constraints and indices
            
            # Expenses table with improved schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount REAL NOT NULL CHECK (amount > 0),
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Add index for frequent queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)')
            
            # Budgets table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS budgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT UNIQUE NOT NULL,
                    limit_amount REAL NOT NULL CHECK (limit_amount >= 0),
                    spent_amount REAL DEFAULT 0 CHECK (spent_amount >= 0),
                    period TEXT DEFAULT 'monthly'
                )
            ''')
            
            # Savings goals table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS savings_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_name TEXT UNIQUE NOT NULL,
                    target_amount REAL NOT NULL CHECK (target_amount > 0),
                    current_savings REAL DEFAULT 0 CHECK (current_savings >= 0),
                    deadline DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Notifications table with improved schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'unread' CHECK (status IN ('read', 'unread')),
                    type TEXT DEFAULT 'info' CHECK (type IN ('info', 'warning', 'alert')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create default budgets if they don't exist
            default_budgets = [
                ("food", 500),
                ("housing", 1500),
                ("transport", 300),
                ("entertainment", 200),
                ("shopping", 300),
                ("health", 300),
                ("other", 200)
            ]
            
            for category, amount in default_budgets:
                cursor.execute('''
                    INSERT OR IGNORE INTO budgets (category, limit_amount)
                    VALUES (?, ?)
                ''', (category, amount))
            
            conn.commit()
            logger.info("Database initialized successfully")
            return True
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        return False

def categorize_expense(description):
    """Categorize expense using keyword matching with improved algorithm"""
    if not description:
        return "other"
        
    # More comprehensive category mapping
    categories = {
        "food": ["groceries", "restaurant", "snack", "food", "lunch", "dinner", "breakfast", 
                "cafe", "coffee", "meal", "takeout", "delivery", "dine"],
        "housing": ["rent", "mortgage", "utilities", "electricity", "water", "gas bill", "internet",
                  "repair", "maintenance", "property", "furniture", "home", "apartment"],
        "transport": ["gas", "uber", "bus", "car", "taxi", "train", "subway", "lyft", "fuel",
                    "transit", "transportation", "commute", "vehicle", "maintenance", "parking"],
        "entertainment": ["movie", "game", "concert", "theater", "netflix", "subscription", "streaming",
                        "hobby", "leisure", "event", "ticket", "show", "music", "sports"],
        "shopping": ["clothes", "electronics", "shoes", "amazon", "online", "mall", "retail", "purchase",
                   "clothing", "accessory", "device", "gadget", "appliance"],
        "health": ["doctor", "medical", "medicine", "pharmacy", "healthcare", "dental", "vision",
                 "fitness", "gym", "wellness", "hospital", "prescription"]
    }
    
    description = description.lower()
    max_matches = 0
    best_category = "other"
    
    for category, keywords in categories.items():
        matches = sum(1 for keyword in keywords if keyword in description)
        if matches > max_matches:
            max_matches = matches
            best_category = category
    
    return best_category

def add_expense(amount, description, category=None, date=None):
    """Add an expense with improved validation and error handling"""
    try:
        # Validate inputs
        if not amount or float(amount) <= 0:
            raise ValueError("Amount must be a positive number")
        
        if not description:
            raise ValueError("Description cannot be empty")
        
        # Auto-categorize if not provided
        if category is None or category.strip() == "":
            category = categorize_expense(description)
        
        # Handle date properly
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(date, str):
            # Ensure date string is in correct format
            try:
                datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    # Try alternative format
                    date = datetime.strptime(date, '%Y-%m-%d').strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    # If all fails, use current date
                    date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with db_connection() as conn:
            cursor = conn.cursor()
            
            # Use transaction to ensure database consistency
            cursor.execute('BEGIN TRANSACTION')
            
            # Insert the expense
            cursor.execute('''
                INSERT INTO expenses (amount, description, category, date) 
                VALUES (?, ?, ?, ?)
            ''', (amount, description, category, date))
            
            expense_id = cursor.lastrowid
            
            # Update budget in a single query
            cursor.execute('''
                INSERT INTO budgets (category, limit_amount, spent_amount)
                VALUES (?, 300, ?)
                ON CONFLICT(category) DO UPDATE SET
                spent_amount = spent_amount + ?
            ''', (category, amount, amount))
            
            # Check budget status and create notification if needed
            cursor.execute('''
                SELECT limit_amount, spent_amount FROM budgets WHERE category = ?
            ''', (category,))
            
            budget = cursor.fetchone()
            if budget and budget['spent_amount'] > budget['limit_amount']:
                percentage = round((budget['spent_amount'] / budget['limit_amount']) * 100)
                
                # Decide notification type based on severity
                notification_type = 'warning'
                if percentage > 120:
                    notification_type = 'alert'
                
                cursor.execute('''
                    INSERT INTO notifications (message, status, type)
                    VALUES (?, 'unread', ?)
                ''', (f"Alert: You've exceeded your {category} budget of ${budget['limit_amount']} (currently at {percentage}%)!", notification_type))
            
            conn.commit()
            logger.info(f"Added expense: ${amount} for {description} in {category}")
            
            return expense_id
    except (ValueError, sqlite3.Error) as e:
        logger.error(f"Error adding expense: {e}")
        raise

def get_all_expenses(limit=100, offset=0, category=None, date_from=None, date_to=None):
    """Get expenses with filtering and pagination for UI"""
    try:
        query = '''
            SELECT id, amount, description, category, date 
            FROM expenses 
            WHERE 1=1
        '''
        params = []
        
        # Apply filters if provided
        if category:
            query += " AND category = ?"
            params.append(category)
        
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        
        query += " ORDER BY date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Get total count for pagination
            count_query = '''
                SELECT COUNT(*) FROM expenses WHERE 1=1
            '''
            count_params = []
            
            if category:
                count_query += " AND category = ?"
                count_params.append(category)
            
            if date_from:
                count_query += " AND date >= ?"
                count_params.append(date_from)
            
            if date_to:
                count_query += " AND date <= ?"
                count_params.append(date_to)
            
            cursor.execute(count_query, count_params)
            total_count = cursor.fetchone()[0]
            
            # Format response for UI
            expenses = []
            for row in rows:
                expenses.append({
                    'id': row['id'],
                    'amount': float(row['amount']),  # Format for UI
                    'description': row['description'],
                    'category': row['category'],
                    'date': row['date'],
                    'formatted_date': datetime.strptime(row['date'], '%Y-%m-%d %H:%M:%S').strftime('%b %d, %Y')  # Friendly date
                })
            
            return {
                'expenses': expenses,
                'pagination': {
                    'total': total_count,
                    'page': offset // limit + 1,
                    'limit': limit,
                    'pages': (total_count + limit - 1) // limit
                }
            }
    except sqlite3.Error as e:
        logger.error(f"Error retrieving expenses: {e}")
        raise

def delete_expense(expense_id):
    """Delete an expense with proper transaction handling"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN TRANSACTION')
            
            # Get expense details
            cursor.execute('''
                SELECT amount, category FROM expenses WHERE id = ?
            ''', (expense_id,))
            
            expense = cursor.fetchone()
            
            if not expense:
                conn.rollback()
                raise ValueError(f"Expense with ID {expense_id} not found")
            
            amount, category = expense['amount'], expense['category']
            
            # Delete the expense
            cursor.execute('DELETE FROM expenses WHERE id = ?', (expense_id,))
            
            # Update budget in a single query
            cursor.execute('''
                UPDATE budgets
                SET spent_amount = MAX(0, spent_amount - ?)
                WHERE category = ?
            ''', (amount, category))
            
            conn.commit()
            logger.info(f"Deleted expense ID {expense_id}")
            return True
    except (ValueError, sqlite3.Error) as e:
        logger.error(f"Error deleting expense: {e}")
        raise

def get_expenses_summary(period=None):
    """Get expense summary with optional time period filtering"""
    try:
        query_params = []
        date_filter = ""
        
        if period:
            today = datetime.now()
            if period == 'week':
                # Last 7 days
                date_filter = "WHERE date >= date('now', '-7 days')"
            elif period == 'month':
                # Current month
                date_filter = "WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now')"
            elif period == 'year':
                # Current year
                date_filter = "WHERE strftime('%Y', date) = strftime('%Y', 'now')"
        
        with db_connection() as conn:
            cursor = conn.cursor()
            
            # Get total expenses
            cursor.execute(f'''
                SELECT SUM(amount) FROM expenses {date_filter}
            ''', query_params)
            
            total = cursor.fetchone()[0] or 0
            
            # Get breakdown by category
            cursor.execute(f'''
                SELECT category, SUM(amount) as amount
                FROM expenses
                {date_filter}
                GROUP BY category
                ORDER BY amount DESC
            ''', query_params)
            
            categories = []
            for row in cursor.fetchall():
                categories.append({
                    'category': row[0],
                    'amount': float(row[1]),
                    'percentage': round((float(row[1]) / total * 100) if total > 0 else 0, 1)
                })
            
            # Get day-by-day spending for trend analysis (last 30 days)
            cursor.execute('''
                SELECT date(date) as day, SUM(amount) as daily_total
                FROM expenses
                WHERE date >= date('now', '-30 days')
                GROUP BY day
                ORDER BY day
            ''')
            
            daily_spending = [{'date': row[0], 'amount': float(row[1])} for row in cursor.fetchall()]
            
            return {
                'total_expenses': float(total),
                'categories': categories,
                'daily_trend': daily_spending,
                'period': period or 'all'
            }
    except sqlite3.Error as e:
        logger.error(f"Error getting expense summary: {e}")
        raise

def get_budget_insights(category=None):
    """Get budget insights for UI display"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            if category:
                # Single category insights
                cursor.execute('''
                    SELECT category, limit_amount, spent_amount 
                    FROM budgets WHERE category = ?
                ''', (category,))
                
                result = cursor.fetchone()
                
                if not result:
                    return {"message": f"Budget for '{category}' not found. Please set a budget first."}
                
                limit_amount = float(result['limit_amount'])
                spent_amount = float(result['spent_amount'])
                remaining = limit_amount - spent_amount
                percentage = round((spent_amount / limit_amount * 100) if limit_amount > 0 else 0, 1)
                
                # Calculate status for UI
                status = "good"
                if percentage >= 100:
                    status = "danger"
                elif percentage >= 80:
                    status = "warning"
                
                return {
                    "category": result['category'],
                    "limit_amount": limit_amount,
                    "spent_amount": spent_amount,
                    "remaining": remaining,
                    "percentage": percentage,
                    "status": status,
                    "advice": get_budget_advice(percentage)
                }
            else:
                # All categories summary
                return get_budget_overview()
    except sqlite3.Error as e:
        logger.error(f"Error getting budget insights: {e}")
        raise

def get_budget_advice(percentage):
    """Get context-aware budget advice based on percentage spent"""
    if percentage >= 100:
        return "You've exceeded your budget in this category. Consider reducing your spending or adjusting your budget if needed."
    elif percentage >= 90:
        return "You're very close to reaching your budget limit. Be careful with additional expenses in this category."
    elif percentage >= 75:
        return "You've used most of your budget. Plan carefully for remaining expenses this period."
    elif percentage >= 50:
        return "You're using your budget at a moderate pace. Continue monitoring your spending."
    else:
        return "You're well within your budget. Great job managing your finances!"

def set_budget(category, limit_amount):
    """Set or update a budget with validation"""
    try:
        if not category or not category.strip():
            raise ValueError("Category cannot be empty")
            
        if not limit_amount or float(limit_amount) < 0:
            raise ValueError("Budget limit must be a non-negative number")
            
        with db_connection() as conn:
            cursor = conn.cursor()
            
            # Upsert operation for budget
            cursor.execute('''
                INSERT INTO budgets (category, limit_amount)
                VALUES (?, ?)
                ON CONFLICT(category) DO UPDATE SET
                limit_amount = ?
            ''', (category, float(limit_amount), float(limit_amount)))
            
            conn.commit()
            logger.info(f"Budget set: {category} = ${limit_amount}")
            return True
    except (ValueError, sqlite3.Error) as e:
        logger.error(f"Error setting budget: {e}")
        raise

def add_savings_goal(goal_name, target_amount, deadline=None):
    """Add a savings goal with validation and proper date handling"""
    try:
        if not goal_name or not goal_name.strip():
            raise ValueError("Goal name cannot be empty")
            
        if not target_amount or float(target_amount) <= 0:
            raise ValueError("Target amount must be a positive number")
            
        # Handle deadline date
        if deadline and isinstance(deadline, str):
            try:
                # Validate date format
                datetime.strptime(deadline, '%Y-%m-%d')
            except ValueError:
                deadline = None
        
        with db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if goal with same name exists
            cursor.execute('SELECT goal_name FROM savings_goals WHERE goal_name = ?', (goal_name,))
            if cursor.fetchone():
                raise ValueError(f"A savings goal named '{goal_name}' already exists")
            
            # Insert new goal
            if deadline:
                cursor.execute('''
                    INSERT INTO savings_goals (goal_name, target_amount, deadline)
                    VALUES (?, ?, ?)
                ''', (goal_name, float(target_amount), deadline))
            else:
                cursor.execute('''
                    INSERT INTO savings_goals (goal_name, target_amount)
                    VALUES (?, ?)
                ''', (goal_name, float(target_amount)))
            
            conn.commit()
            logger.info(f"Added savings goal: {goal_name} with target ${target_amount}")
            return cursor.lastrowid
    except (ValueError, sqlite3.Error) as e:
        logger.error(f"Error adding savings goal: {e}")
        raise

def update_savings_goal(goal_id=None, goal_name=None, current_savings=None, target_amount=None):
    """Update a savings goal with flexible parameters"""
    try:
        if not goal_id and not goal_name:
            raise ValueError("Either goal ID or goal name must be provided")
            
        if current_savings is not None and float(current_savings) < 0:
            raise ValueError("Current savings cannot be negative")
            
        if target_amount is not None and float(target_amount) <= 0:
            raise ValueError("Target amount must be positive")
            
        with db_connection() as conn:
            cursor = conn.cursor()
            
            # Find the goal
            if goal_id:
                cursor.execute('SELECT id FROM savings_goals WHERE id = ?', (goal_id,))
            else:
                cursor.execute('SELECT id FROM savings_goals WHERE goal_name = ?', (goal_name,))
                
            goal = cursor.fetchone()
            if not goal:
                raise ValueError(f"Savings goal not found")
                
            # Update parameters that were provided
            updates = []
            params = []
            
            if current_savings is not None:
                updates.append("current_savings = ?")
                params.append(float(current_savings))
                
            if target_amount is not None:
                updates.append("target_amount = ?")
                params.append(float(target_amount))
                
            if updates:
                query = f"UPDATE savings_goals SET {', '.join(updates)} WHERE id = ?"
                params.append(goal['id'])
                cursor.execute(query, params)
                
                conn.commit()
                logger.info(f"Updated savings goal ID {goal['id']}")
                return True
            else:
                return False
    except (ValueError, sqlite3.Error) as e:
        logger.error(f"Error updating savings goal: {e}")
        raise

def get_savings_goals():
    """Get all savings goals with progress information"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, goal_name, target_amount, current_savings, deadline, created_at
                FROM savings_goals
                ORDER BY created_at DESC
            ''')
            
            rows = cursor.fetchall()
            goals = []
            
            for row in rows:
                target = float(row['target_amount'])
                current = float(row['current_savings'])
                percentage = round((current / target * 100) if target > 0 else 0, 1)
                
                goals.append({
                    'id': row['id'],
                    'name': row['goal_name'],
                    'target_amount': target,
                    'current_savings': current,
                    'deadline': row['deadline'],
                    'progress': percentage,
                    'created_at': row['created_at']
                })
            
            return goals
    except sqlite3.Error as e:
        logger.error(f"Error retrieving savings goals: {e}")
        raise

def get_notifications(limit=5, include_read=False):
    """Get notifications with improved filtering"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            status_filter = "" if include_read else "WHERE status = 'unread'"
            
            cursor.execute(f'''
                SELECT id, message, status, type, created_at 
                FROM notifications
                {status_filter}
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
            
            notifications = []
            for row in cursor.fetchall():
                notifications.append({
                    "id": row['id'],
                    "message": row['message'],
                    "status": row['status'],
                    "type": row['type'],
                    "date": row['created_at'],
                    "formatted_date": datetime.strptime(row['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%b %d, %H:%M')
                })
            
            return notifications
    except sqlite3.Error as e:
        logger.error(f"Error retrieving notifications: {e}")
        raise

def mark_notification_read(notification_id):
    """Mark a notification as read with validation"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM notifications WHERE id = ?', (notification_id,))
            if not cursor.fetchone():
                raise ValueError(f"Notification ID {notification_id} not found")
                
            cursor.execute('''
                UPDATE notifications
                SET status = 'read'
                WHERE id = ?
            ''', (notification_id,))
            
            conn.commit()
            return True
    except (ValueError, sqlite3.Error) as e:
        logger.error(f"Error retrieving notifications: {e}")
        raise

def get_budget_overview():
    """Get comprehensive budget overview with status and summary statistics"""
    try:
        with db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get budget data with percentage calculation in SQL
            cursor.execute('''
                SELECT 
                    category, 
                    limit_amount, 
                    spent_amount,
                    CASE WHEN limit_amount > 0 
                        THEN (spent_amount / limit_amount) * 100
                        ELSE 0 
                    END as percentage
                FROM budgets
                ORDER BY percentage DESC
            ''')
            
            results = []
            total_limit = 0
            total_spent = 0
            
            for row in cursor.fetchall():
                category = row['category']
                limit = row['limit_amount']
                spent = row['spent_amount']
                percentage = row['percentage']
                remaining = limit - spent
                
                # Track totals for summary
                total_limit += limit
                total_spent += spent
                
                # Determine budget status
                if percentage >= 100:
                    status = "exceeded"
                elif percentage >= 80:
                    status = "warning"
                else:
                    status = "normal"
                    
                results.append({
                    'category': category,
                    'limit': round(limit, 2),
                    'spent': round(spent, 2),
                    'remaining': round(remaining, 2),
                    'percentage': round(percentage, 1),
                    'status': status
                })
            
            # Add summary information
            summary = {
                'total_limit': round(total_limit, 2),
                'total_spent': round(total_spent, 2),
                'total_remaining': round(total_limit - total_spent, 2),
                'overall_percentage': round((total_spent / total_limit * 100) if total_limit > 0 else 0, 1)
            }
            
            return {
                'categories': results,
                'summary': summary
            }
    except sqlite3.Error as e:
        logger.error(f"Error retrieving budget overview: {e}")
        raise

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")