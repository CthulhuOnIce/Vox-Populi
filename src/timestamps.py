import datetime

def timestamp(datetime:datetime.datetime):  # 2022-10-19 21:02:28
    return datetime.strftime("%Y-%m-%d %H:%M:%S")

def short_text(datetime:datetime.datetime):  # Oct 19, 2022 09:13 PM
    return datetime.strftime("%b %d, %Y %I:%M %p")

def long_text(datetime:datetime.datetime): # October 19, 2022 at 9:03 PM
    return datetime.strftime("%B %e, %Y at %l:%M %p")

def simple_day(datetime:datetime.datetime):  # 19 October 2022
    return datetime.strftime("%d %B %Y")

def simple_datetime(datetime:datetime.datetime):  # 19 October 2022 at 9:03 PM
    return datetime.strftime("%d %B %Y at %l:%M %p")