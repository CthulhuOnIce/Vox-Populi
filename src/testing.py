import datetime
import sys

import colorama
import yaml
from discord.ext import commands
from mongomock_motor import AsyncMongoMockClient

from . import database, debug, legislation, offices

C = {}
tests = []
passed = 0
failed = 0
bot:commands.bot = None

class Test:
    function = None
    name = None
    bot = None

    def __init__(self, function, name):
        self.function = function
        self.name = name
        tests.append(self)

    async def run_test(self):
        global passed
        global failed
        try:
            await self.function()
            print(f"{colorama.Fore.GREEN}✅ Test '{self.name}' passed{colorama.Fore.RESET}")
            passed += 1
        except Exception as e:
            print(f"{colorama.Fore.RED}❌ Test '{self.name}' failed{colorama.Fore.RESET}")
            print(f"{colorama.Fore.RED}Error: {e}{colorama.Fore.RESET}")
            failed += 1

async def swap_database():
    database.client = AsyncMongoMockClient()

Test(swap_database, "Swap database")

async def populate_offices():
    await database.Elections.populate_offices()
    con = await database.create_connection("Offices")
    offices_ = await con.find().to_list(None)
    assert len(offices_) == 1
    await offices.populate(bot, C)
    assert len(offices.Offices) == 1

Test(populate_offices, "Populate offices")

async def submit_motion():
    template_motion = {
        "Heading": {
            "Title": "Test Motion",
            "Description": "The description of the motion. This goes into more detail on the intention and effects, and acts as an explainer and first press release.",
        },
        "Guild": {
            "Name": "Guild Name",
        }
    }
    new_id = await database.Motions.submit_new_motion(bot.user.id, template_motion, yaml.dump(template_motion))

Test(submit_motion, "Submit test motion")

async def defeat_motion():
    con = await database.create_connection("Motions")
    await con.update_many({}, {"$set": {"expires": datetime.datetime.now() - datetime.timedelta(days=1)}})
    legislation = bot.get_cog("Legislation")
    await legislation.motion_check_loop()

Test(defeat_motion, "Defeat motion")

async def archive_motion():
    con = await database.create_connection("Archive-Motions")
    res = await con.find().to_list(None)
    assert len(res) == 1

Test(archive_motion, "Archive motion")

async def check_constitution():
    const = await database.Constitution.get_constitution()
    if not "_id" in const:
        ValueError("Constitution did not write to db")
    const.pop("_id")  # now take it out to compare to template
    assert const == database.Constitution.default_constitution

Test(check_constitution, "Check constitution")

async def test(bot_, C_):
    global bot
    global C

    bot = bot_
    C = C_

    print(f"Running {len(tests)} tests...")
    for test in tests:
        await test.run_test()
    print(f"{colorama.Fore.GREEN}Tests passed: {passed}{colorama.Fore.RESET}")
    print(f"{colorama.Fore.RED if failed else colorama.Fore.GREEN}Tests failed: {failed}{colorama.Fore.RESET}")
    if failed:
        if passed:
            print(f"{colorama.Fore.YELLOW}Some tests failed{colorama.Fore.RESET}")
        else:
            print(f"{colorama.Fore.RED}All tests failed{colorama.Fore.RESET}")
    else:
        print(f"{colorama.Fore.GREEN}All tests passed{colorama.Fore.RESET}")

    sys.exit(failed)
    
