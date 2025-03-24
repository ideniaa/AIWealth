import os
import json
import pandas as pd
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime
import plotly
import plotly.express as px
import traceback  # For error tracking
from database import (
    init_db, 
    add_expense as db_add_expense, 
    get_budget_insights,
    set_budget as db_set_budget,
    get_all_expenses,
    delete_expense as db_delete_expense,
    get_expenses_summary,
    get_budget_overview,
    categorize_expense
)

# Load environment variables
load_dotenv()

# Initialize database
init_db()

# Configure Gemini API
api_key = os.getenv("GEMINI_API_KEY")

if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        print("Gemini API configured successfully")
    except Exception as e:
        print(f"Warning: Failed to configure Gemini API: {str(e)}")
        model = None
else:
    model = None
    print("Warning: GEMINI_API_KEY not found in .env file")

# Initialize system prompt with financial advisor context
SYSTEM_PROMPT = """
You are AIWealth, a helpful and knowledgeable financial advisor chatbot. Your goal is to provide personalized financial guidance based on users' situations.

Your capabilities include:
- Helping with budgeting and expense tracking
- Providing basic tax guidance
- Assisting with financial planning and goal setting
- Offering general investment education
- Helping with debt management strategies
- Explaining financial concepts in simple terms

If the user shares expenses or financial data with you, analyze it and provide insights on:
- Major spending categories
- Potential areas to reduce expenses
- Savings opportunities
- Budget recommendations

Please be supportive, non-judgmental, and focused on helping users improve their financial wellbeing.

If asked about specific investments or complex tax situations, kindly explain that you can provide general guidance but recommend consulting with a certified financial professional for specific advice.
"""

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "aiwealth-secret-key")

# Store chat histories in memory
chat_histories = {}

def parse_expense_message(message):
    """Extract expense details from chat messages like 'Add $45 for groceries'"""
    message = message.lower().strip()
    
    print(f"Attempting to parse expense from: '{message}'")
    
    # Look for expense patterns
    expense_triggers = ["add", "spent", "paid", "bought", "purchased"]
    has_trigger = any(trigger in message for trigger in expense_triggers)
    has_amount = "$" in message
    has_description = any(connector in message for connector in ["for", "on", "at"])
    
    if has_trigger and has_amount and has_description:
        try:
            # Extract amount using dollar sign as reference
            parts = message.split("$")
            amount_part = parts[1].split()[0].replace(',', '')
            # Handle decimal points
            amount = float(amount_part)
            
            # Extract description - everything after "for" or "on"
            if "for" in message:
                description_part = message.split("for")[1].strip()
            elif "on" in message:
                description_part = message.split("on")[1].strip()
            elif "at" in message:
                description_part = message.split("at")[1].strip()
            else:
                description_part = message.split("$")[1].split(None, 1)[1].strip() if len(message.split("$")[1].split()) > 1 else "misc expense"
            
            # Use the database categorization function
            category = categorize_expense(description_part)
            
            print(f"Successfully parsed expense: ${amount} for {description_part} (Category: {category})")
            
            return {
                "amount": amount,
                "description": description_part,
                "category": category
            }
        except Exception as e:
            print(f"Error parsing expense message: {str(e)}")
            return None
    
    print("Message does not match expense pattern")
    return None

@app.route('/')
def index():
    # Generate a session ID if none exists
    if 'user_id' not in session:
        session['user_id'] = f"user_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Initialize chat history for this user if needed
    user_id = session['user_id']
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '')
    user_id = session.get('user_id', 'default_user')
    
    if not user_message:
        return jsonify({"response": "No message provided"})
    
    try:
        # Check if message is about adding an expense
        expense_info = parse_expense_message(user_message)
        if expense_info:
            # Add expense to the database
            expense_id = db_add_expense(
                expense_info['amount'],
                expense_info['description'],
                expense_info['category']
            )
            
            # Send response about added expense
            category_name = expense_info['category'].capitalize()
            response_text = f"I've added your expense of ${expense_info['amount']:.2f} for {expense_info['description']} in the {category_name} category. You can view your spending breakdown in the dashboard."
            
            # Store response in chat history
            if user_id not in chat_histories:
                chat_histories[user_id] = []
            
            chat_histories[user_id].append({"role": "user", "parts": [user_message]})
            chat_histories[user_id].append({"role": "model", "parts": [response_text]})
            
            return jsonify({"response": response_text})
        
        # Parse budget setting commands
        if ("set budget" in user_message.lower() or "set a budget" in user_message.lower()) and "for" in user_message.lower() and "to" in user_message.lower():
            message = user_message.lower()
            # Extract category and amount
            split_for = message.split("for")[1]
            category_part = split_for.split("to")[0].strip()
            amount_part = split_for.split("to")[1].strip()
            
            # Remove dollar sign if present
            if "$" in amount_part:
                amount_part = amount_part.replace("$", "")
            
            try:
                amount = float(amount_part.replace(',', ''))
                
                # Store budget in database
                db_set_budget(category_part, amount)
                
                response_text = f"I've set your budget for {category_part} to ${amount:.2f}."
                
                # Store response in chat history
                if user_id not in chat_histories:
                    chat_histories[user_id] = []
                
                chat_histories[user_id].append({"role": "user", "parts": [user_message]})
                chat_histories[user_id].append({"role": "model", "parts": [response_text]})
                
                return jsonify({"response": response_text})
            except ValueError:
                pass
        
        # Regular chat processing for non-expense messages
        if user_id not in chat_histories:
            chat_histories[user_id] = []
        
        # Add the user message to chat history
        chat_histories[user_id].append({"role": "user", "parts": [user_message]})
        
        # If the Gemini API is configured
        if model:
            # If this is the first message, include the system prompt
            if len(chat_histories[user_id]) == 1:
                response = model.generate_content([SYSTEM_PROMPT, user_message])
            else:
                # Create conversation context from chat history
                convo = model.start_chat(history=chat_histories[user_id][:-1])
                response = convo.send_message(user_message)
            
            # Add the AI response to chat history
            bot_response = response.text
        else:
            # If Gemini API is not configured, use a fallback response
            bot_response = "I'm currently running in limited mode. Please configure a Gemini API key to enable all features."
        
        chat_histories[user_id].append({"role": "model", "parts": [bot_response]})
        
        return jsonify({"response": bot_response})
    
    except Exception as e:
        print(f"Error in chat route: {str(e)}")
        traceback.print_exc()
        return jsonify({"response": f"I'm sorry, I encountered an error processing your request."})

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id', 'default_user')
    
    try:
        # Get expenses from database
        expenses = get_all_expenses()
        
        if not expenses:
            print("No expense data found in database")
            return render_template('dashboard.html', has_data=False)
        
        # Process expense data for the dashboard
        df = pd.DataFrame(expenses)
        
        # Create category summary
        category_summary = df.groupby('category')['amount'].sum().reset_index()
        
        # Prepare data for Chart.js
        categories = category_summary['category'].tolist()
        amounts = category_summary['amount'].tolist()
        
        # Get total expenses and top categories
        total_expenses = df['amount'].sum()
        top_categories = category_summary.sort_values('amount', ascending=False).head(3)
        
        # Get budget information
        budget_overview = get_budget_overview()
                
        # Calculate monthly average (if dates are available)
        monthly_avg = total_expenses
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            # Get date range in days, convert to months
            date_range = (df['date'].max() - df['date'].min()).days
            months = max(1, date_range / 30)
            monthly_avg = total_expenses / months
        
        # Prepare data for the template
        return render_template(
            'dashboard.html',
            has_data=True,
            categories=categories,
            amounts=amounts,
            total_expenses=total_expenses,
            top_categories=top_categories.to_dict('records'),
            monthly_avg=monthly_avg,
            expenses=expenses,
            budget_overview=budget_overview
        )
    except Exception as e:
        print(f"Error in dashboard route: {str(e)}")
        traceback.print_exc()
        return render_template('dashboard.html', has_data=False, 
                              error=f"Error generating dashboard: {str(e)}")
    
@app.route('/add_expense', methods=['POST'])
def add_expense():
    try:
        # Get expense details from form
        amount = float(request.form.get('amount', 0))
        category = request.form.get('category', 'other')
        description = request.form.get('description', '')
        
        # Add expense to database
        db_add_expense(amount, description, category)
        
        return redirect('/dashboard')
    except ValueError:
        return "Invalid amount value", 400
    except Exception as e:
        print(f"Error adding expense: {str(e)}")
        traceback.print_exc()
        return f"Error adding expense: {str(e)}", 500

@app.route('/delete_expense/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    try:
        # Delete expense from database
        db_delete_expense(expense_id)
        return redirect('/dashboard')
    except Exception as e:
        print(f"Error deleting expense: {str(e)}")
        return f"Error deleting expense: {str(e)}", 500

@app.route('/analyze_expenses', methods=['POST'])
def analyze_expenses():
    try:
        # Get expense summary from database
        expense_summary_data = get_expenses_summary()
        
        if not expense_summary_data or expense_summary_data['total_expenses'] == 0:
            return jsonify({"response": "No expense data available to analyze"})
        
        # Format expenses for the AI to analyze
        total_expenses = expense_summary_data['total_expenses']
        categories = expense_summary_data['categories']
        
        # Create a summary of expenses for analysis
        expense_summary = "Here's my expense data:\n"
        expense_summary += f"Total expenses: ${total_expenses:.2f}\n"
        expense_summary += "Breakdown by category:\n"
        
        for category in categories:
            percentage = (category['amount'] / total_expenses) * 100
            expense_summary += f"- {category['category']}: ${category['amount']:.2f} ({percentage:.1f}%)\n"
        
        expense_summary += "\nCan you analyze my spending and provide recommendations?"
        
        # Send this data to the AI for analysis
        if model:
            response = model.generate_content([
                "You are a financial advisor analyzing expense data. Provide specific insights and recommendations.",
                expense_summary
            ])
            ai_response = response.text
        else:
            ai_response = "AI analysis is currently unavailable. Please configure a Gemini API key to enable this feature."
        
        return jsonify({"response": ai_response})
    
    except Exception as e:
        print(f"Error analyzing expenses: {str(e)}")
        traceback.print_exc()
        return jsonify({"response": "I'm sorry, I encountered an error while analyzing your expenses."})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)