"""Hostile mock banking application for testing SynthScript."""

from flask import Flask, render_template_string, request

app = Flask(__name__)


MAIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Legacy Banking System</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f0f0f0; }
        .header { background: #003366; color: white; padding: 10px; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; }
        table { border-collapse: collapse; width: 100%; }
        td { border: 1px solid #ddd; padding: 8px; }
        .nested-table { width: 100%; }
        .button { background: #003366; color: white; padding: 10px 20px; border: none; cursor: pointer; }
        .button:hover { background: #004488; }
        .error { color: red; font-weight: bold; }
        .success { color: green; font-weight: bold; }
        iframe { width: 100%; height: 400px; border: 1px solid #ccc; }
    </style>
</head>
<body>
    <div class="header">
        <table>
            <tr>
                <td><h1>Legacy Banking System v2.0</h1></td>
                <td style="text-align: right;">Welcome, User</td>
            </tr>
        </table>
    </div>
    
    <div class="container">
        <table>
            <tr>
                <td colspan="2">
                    <h2>Member Lookup</h2>
                </td>
            </tr>
            <tr>
                <td colspan="2">
                    <iframe src="/iframe-form" id="member-lookup-frame"></iframe>
                </td>
            </tr>
        </table>
        
        <table style="margin-top: 20px;">
            <tr>
                <td><strong>Quick Links:</strong></td>
                <td>
                    <a href="#">Account Summary</a> |
                    <a href="#">Transfer Funds</a> |
                    <a href="#">Bill Pay</a>
                </td>
            </tr>
        </table>
    </div>
</body>
</html>
"""

IFRAME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Member Lookup Form</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 10px; background: #ffffff; }
        table { border-collapse: collapse; width: 100%; }
        td { padding: 8px; border: 1px solid #ddd; }
        input[type="text"] { width: 200px; padding: 5px; }
        .button { background: #003366; color: white; padding: 8px 16px; border: none; cursor: pointer; }
        .button:hover { background: #004488; }
        .result-table { margin-top: 20px; }
        .error { color: red; font-weight: bold; padding: 10px; background: #ffeeee; }
    </style>
</head>
<body>
    <table>
        <tr>
            <td colspan="2">
                <h3>Member Search</h3>
            </td>
        </tr>
        <tr>
            <td><strong>Member ID:</strong></td>
            <td>
                <input type="text" id="member-id-input" placeholder="Enter Member ID">
            </td>
        </tr>
        <tr>
            <td colspan="2" style="text-align: center;">
                <button class="button" id="search-button">Search</button>
            </td>
        </tr>
    </table>
    
    {% if error %}
    <div class="error">{{ error }}</div>
    {% endif %}
    
    {% if result %}
    <table class="result-table">
        <tr>
            <td colspan="2"><strong>Search Results:</strong></td>
        </tr>
        <tr>
            <td><strong>Member ID:</strong></td>
            <td>{{ result.member_id }}</td>
        </tr>
        <tr>
            <td><strong>Name:</strong></td>
            <td>{{ result.name }}</td>
        </tr>
        <tr>
            <td><strong>Account Balance:</strong></td>
            <td>${{ result.balance }}</td>
        </tr>
        <tr>
            <td><strong>Status:</strong></td>
            <td>{{ result.status }}</td>
        </tr>
    </table>
    {% endif %}
    
    <script>
        document.getElementById('search-button').addEventListener('click', function() {
            var memberId = document.getElementById('member-id-input').value;
            fetch('/search?member_id=' + encodeURIComponent(memberId))
                .then(response => response.text())
                .then(html => {
                    document.body.innerHTML = html;
                });
        });
    </script>
</body>
</html>
"""


# Mock database
MEMBERS = {
    "12345": {"member_id": "12345", "name": "John Smith", "balance": "15,234.56", "status": "Active"},
    "67890": {"member_id": "67890", "name": "Jane Doe", "balance": "8,765.43", "status": "Active"},
    "11111": {"member_id": "11111", "name": "Bob Johnson", "balance": "45,123.00", "status": "Inactive"},
}


@app.route("/")
def index():
    """Main page with nested tables and iframe."""
    return render_template_string(MAIN_TEMPLATE)


@app.route("/iframe-form")
def iframe_form():
    """The iframe containing the actual form."""
    error = request.args.get("error")
    result = request.args.get("result")
    
    if result:
        import json
        result_data = json.loads(result)
        return render_template_string(IFRAME_TEMPLATE, error=error, result=result_data)
    
    return render_template_string(IFRAME_TEMPLATE, error=error, result=None)


@app.route("/search")
def search():
    """Search endpoint - deliberately hostile with 999 returning error."""
    member_id = request.args.get("member_id", "")
    
    if member_id == "999":
        # Deliberate failure state
        return render_template_string(IFRAME_TEMPLATE, error="Record not found. Please check the Member ID and try again.", result=None)
    
    if member_id in MEMBERS:
        import json
        return render_template_string(IFRAME_TEMPLATE, error=None, result=MEMBERS[member_id])
    
    if member_id:
        return render_template_string(IFRAME_TEMPLATE, error="No record found for Member ID: " + member_id, result=None)
    
    return render_template_string(IFRAME_TEMPLATE, error="Please enter a Member ID", result=None)


def create_app():
    """Application factory for tests that expect create_app().

    Returns the pre-configured Flask app instance used by the test mock app.
    """
    return app


if __name__ == "__main__":
    app.run(debug=True, port=5000)
