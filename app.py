import os
import json
import requests
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
from openai import OpenAI  # Updated import
from datetime import datetime
from dateutil.relativedelta import relativedelta
from anthropic import Anthropic

from dotenv import load_dotenv
load_dotenv()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Initialize Flask app
app = Flask(__name__)

# Print current working directory
print("Current directory:", os.getcwd())

# Load .env file
print("\nLoading .env file...")
load_dotenv(verbose=True)

# Set API keys from environment variables
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Print environment variables status
print("\nAPI Keys loaded:")
print("NEWS_API_KEY present:", bool(NEWS_API_KEY))
print("OPENAI_API_KEY prefix:", OPENAI_API_KEY[:7] if OPENAI_API_KEY else "Not found")
print("ANTHROPIC_API_KEY present:", bool(ANTHROPIC_API_KEY))

# Set Flask secret key
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your_secret_key_here")

# Initialize API clients
client = OpenAI(api_key=OPENAI_API_KEY)  # Updated OpenAI client initialization
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

def extract_query_parameters(user_prompt):
    try:
        response = client.chat.completions.create(  # Updated to use new client
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Extract structured search parameters for a News API query."},
                {"role": "user", "content": f"""
                    Extract search parameters for a news query.
                    Output JSON with these keys:
                    - "keywords": search term string
                    - "relative_time": if mentioned (e.g., "past_week" or "past_month")
                    - "from_date": if absolute start date given (YYYY-MM-DD format)
                    - "to_date": if absolute end date given (YYYY-MM-DD format)
                    - "language": news language (default "en")
                    - "domains": news source domain (optional)
                    
                    Request: "{user_prompt}"
                """}
            ],
            temperature=0,
        )
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        print("Error extracting parameters:", e)
        raise

def extract_comparative_query_parameters(user_prompt):
    try:
        response = client.chat.completions.create(  # Updated to use new client
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Extract structured search parameters for two News API queries."},
                {"role": "user", "content": f"""
                    Extract parameters for two news queries (separated by "vs").
                    Output JSON with "dataset1" and "dataset2" keys, each containing:
                    - "keywords"
                    - "relative_time"
                    - "from_date"
                    - "to_date"
                    - "language"
                    - "domains" (optional)
                    
                    Request: "{user_prompt}"
                """}
            ],
            temperature=0,
        )
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        print("Error extracting comparative parameters:", e)
        raise

def apply_relative_dates(params):
    today = datetime.today()
    params["to_date"] = today.strftime("%Y-%m-%d")
    relative_time = params.get("relative_time", "").lower()
    if relative_time == "past_week":
        params["from_date"] = (today - relativedelta(weeks=1)).strftime("%Y-%m-%d")
    elif relative_time == "past_month":
        params["from_date"] = (today - relativedelta(months=1)).strftime("%Y-%m-%d")
    else:
        params["from_date"] = params.get("from_date", "")
    return params

def fetch_news(params):
    base_url = "https://newsapi.org/v2/everything"
    query_params = {
        "q": params.get("keywords", ""),
        "language": params.get("language", "en"),
        "apiKey": NEWS_API_KEY,
        "sortBy": "relevancy",
        "pageSize": 100
    }
    
    if params.get("from_date"):
        query_params["from"] = params["from_date"]
    if params.get("to_date"):
        query_params["to"] = params["to_date"]
    if params.get("domains"):
        query_params["domains"] = params.get("domains")
        
    try:
        response = requests.get(base_url, params=query_params)
        response.raise_for_status()
        return response.json().get("articles", [])
    except requests.exceptions.RequestException as e:
        print(f"News API error: {str(e)}")
        if response.status_code != 200:
            print("Response:", response.text)
        raise

def query_claude(json_response, user_query):
    try:
        message = anthropic.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=4096,
            temperature=0,
            system="You are a news analysis assistant. Analyze the provided news data and create a comprehensive dashboard with insights about the coverage, trends, and patterns.",
            messages=[{
                "role": "user",
                "content": f"Analyze this news data and create a detailed dashboard:\n\nData: {json_response}\n\nQuery: {user_query}"
            }]
        )
        return message.content
    except Exception as e:
        print(f"Claude API error: {str(e)}")
        raise

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        user_query = request.form.get("query")
        if not user_query:
            flash("Please enter a query.")
            return redirect(url_for("index"))
        return redirect(url_for("result", q=user_query))
    return render_template("simple_index.html")

@app.route("/result")
def result():
    user_query = request.args.get("q")
    if not user_query:
        flash("No query provided.")
        return redirect(url_for("index"))
    
    try:
        if ("vs" in user_query.lower()) or ("compare" in user_query.lower()):
            query_params = extract_comparative_query_parameters(user_query)
            query_params["dataset1"] = apply_relative_dates(query_params["dataset1"])
            query_params["dataset2"] = apply_relative_dates(query_params["dataset2"])
            
            articles1 = fetch_news(query_params["dataset1"])
            articles2 = fetch_news(query_params["dataset2"])
            
            response_data = {
                "query_type": "comparative",
                "query_params": query_params,
                "articles_dataset1": articles1,
                "articles_dataset2": articles2
            }
        else:
            query_params = extract_query_parameters(user_query)
            query_params = apply_relative_dates(query_params)
            articles = fetch_news(query_params)
            
            response_data = {
                "query_type": "single",
                "query_params": query_params,
                "articles": articles
            }
        
        formatted_json = json.dumps(response_data, indent=2)
        claude_response = query_claude(formatted_json, user_query)
        
        return render_template(
            "simple_result.html",
            q=user_query,
            json_data=formatted_json,
            claude_response=claude_response
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Full error traceback:")
        print(error_details)
        flash(f"Error: {str(e)}")
        return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, port=5001)  # Changed port to 5001