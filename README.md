**# Burnside Attendance

A simple student attendance web app made for Burnside High School.

The idea is pretty straightforward: students sign in with their Burnside Google account, check in for Period 1, and can view their own attendance history. There is also an admin area for managing users and attendance.

## Features

- Google sign-in using Burnside school accounts
- Only allows `@burnside.school.nz` accounts
- Student check-in system
- School network/IP checking
- Students can view their own attendance
- Admin dashboard
- Admin-only attendance controls
- User management
- Google profile pictures
- SQLite database
- Responsive design for desktop and mobile

## How it works

Students sign in using their Burnside Google account.

The app checks that the account uses the Burnside school domain:

`@burnside.school.nz`

If the student doesn't already have an account, one is automatically created.

Once signed in, the student can check in for Period 1. Before allowing the check-in, the app checks the user's IP address against the approved school networks.

Students can then open **My Attendance** to see their recorded check-ins.

## Admin access

Admin access is controlled using a list of approved email addresses in `app.py`.

For example:

```python
ADMIN_EMAILS = {
    "22298@burnside.school.nz"
}

If the signed-in account matches an address in this list, the admin features become available.

The admin page is also protected on the server, so users can't access it just by knowing the /admin URL.

Project structure
Burnside-Attendance/
│
├── app.py
├── main.db
├── attendance.db
├── requirements.txt
├── .env
│
├── templates/
│   ├── Home.html
│   ├── attendance.html
│   ├── admin.html
│   ├── account.html
│   ├── checkin.html
│   ├── login.html
│   └── Teacher.html
│
└── static/
    ├── app.css
    ├── script.js
    ├── burnside-building.jpg
    └── uploads/
Running locally

You'll need Python installed.

Clone the repository:

git clone https://github.com/yourusername/burnside-attendance.git
cd burnside-attendance

Install the required packages:

pip install -r requirements.txt

Create a .env file containing the required environment variables:

KEY=your-secret-key

GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

USERNAME=your-email
PASSWORD=your-password

Then start the application:

python app.py

The app will normally be available at:

http://localhost:5000
Google Login

The application uses Google OAuth for authentication.

The Google OAuth callback for a local installation is:

http://localhost:5000/auth/google/callback

For a deployed version, the callback URL needs to match the URL configured in Google Cloud.

The app requests access to:

OpenID
Email
Profile

Students don't need to create or remember another password.

School network checking

Check-ins are restricted using the SCHOOL_NETWORKS dictionary in app.py.

Example:

SCHOOL_NETWORKS = {
    "Burnside WiFi": [
        "202.150.123.193/32",
        "122.63.129.201/32",
        "202.36.179.108/32",
    ],
}

The app checks the IP address of the request against the approved networks before allowing the student to check in.

This is intended to prevent students from checking in when they aren't on an approved network.

If the school's public IP addresses change, these values will need to be updated.

Database

The application currently uses two SQLite databases.

main.db

Stores user information including:

Username
Email
Student code
Profile picture
Verification information
attendance.db

Stores attendance records including:

Student
Check-in time

The databases are created automatically when the application starts.

Deployment

The app can be deployed to services such as Render.

Environment variables should be added through the hosting provider rather than committed to GitHub.

The .env file should never be committed to the repository.

A basic .gitignore should include:

.env
__pycache__/
*.pyc
Built with
Python
Flask
SQLite
HTML
CSS
JavaScript
Google OAuth
Authlib
Flask-Mail
Future improvements

There are still quite a few things I'd like to improve.

Some ideas include:

Storing the full date as well as the check-in time
Supporting multiple school periods
Better attendance statistics
More detailed admin controls
Improved mobile navigation
Better attendance summaries
Improving the network verification system
Cleaning up the database structure
Why I made it

This project started as an idea for a simple attendance and student check-in system for Burnside High School.

It's also been a good project for learning Flask, SQLite, authentication, OAuth, deployment, HTML, CSS and JavaScript.

It's still a work in progress, but the main attendance system is up and running.

Burnside Attendance

Made for Burnside High School.**
