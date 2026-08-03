import smtplib
import ssl

email = "emailer054@gmail.com"
password = "YOUR_NEW_APP_PASSWORD"

context = ssl.create_default_context()

server = smtplib.SMTP_SSL(
    "smtp.gmail.com",
    465,
    context=context
)

server.login(email, password)

print("LOGIN SUCCESS")

server.quit()