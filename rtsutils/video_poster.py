from optparse import OptionParser
from datetime import datetime, timedelta
import time
import random
import os


from video_hit import *
from db_connection import *
from mt_connection import *
from timeutils import total_seconds
from video_approver import approve_video_hits_and_clean_up
from work_approver import expire_all_hits
from break_handler import BreakHandler
import video_hit
import video_encoder
import settings

TIME_BETWEEN_RUNS = 30 # seconds
VIDEO_DIRECTORY = '../web/media/videos/'

MIN_ON_RETAINER = 3

def postRandomHITs(num_hits, max_wait_time, price, expiration, mt_conn, db):
    """ Posts HITs of several possible varieties (creating multiple HIT groups) based on a random selection: will vary price and description """
    
    if random.random() > .5:
        price += 0.01
    
    if random.random() < .5:
        # defaults
        postHITs(num_hits, max_wait_time, price, expiration, mt_conn, db)
    else:
        title = "TurkCamera: help take a good picture"
        description = "I took a short movie rather than a picture. Help find the best photographic moments in it."        
        postHITs(num_hits, max_wait_time, price, expiration, mt_conn, db, title, description)        

def postHITs(num_hits, max_wait_time, price, expiration, mt_conn, db, title = video_hit.TITLE, description = video_hit.DESCRIPTION):
    """ Posts HITs to MTurk with the given parameters"""

    h = VideoHit(waitbucket=max_wait_time,
                reward_as_usd_float=price,
                assignment_duration=max_wait_time+120,
                lifetime=expiration, title=title, description=description)

    for i in range(num_hits):
        try:
            hit = h.post(mt_conn, db)
            print "Posted HIT ID " + hit.HITId
        except Exception, e:
            print "Got exception posting HIT:\n" + str(e)

def quikTurKit(num_hits, max_wait_time, price, expiration):
    """ Keeps posting HITs """
    mt_conn = get_mt_conn()
    db = DBConnection()
    
    try:
        while True:
            start_run = datetime.now()
            printCurrentlyWaiting(db)
            
            postRandomHITs(num_hits, max_wait_time, price, expiration, mt_conn, db)
            approve_video_hits_and_clean_up(verbose=False, dry_run=False)
            postNewVideos(db)
            
            sleep(start_run)
    except KeyboardInterrupt:
        print("Caught Ctrl-C. Exiting...")
        expire_all_hits(mt_conn)
        approve_video_hits_and_clean_up(verbose=False, dry_run=False)


def printCurrentlyWaiting(db):
    ping_floor = datetime.now() - timedelta(seconds = 10)
    ping_types = ["ping-waiting", "ping-showing", "ping-working"]

    results = dict()
    for ping_type in ping_types:
        row = db.query_and_return_array("""SELECT COUNT(DISTINCT assignmentid) FROM logging WHERE event='%s' AND servertime >= %s""" % ( ping_type, unixtime(ping_floor) ))[0]
        results[ping_type] = row['COUNT(DISTINCT assignmentid)']

        print(ping_type + ": unique assignmentIds pings in last 15 seconds: " + str(results[ping_type]))
    return results


def sleep(start_run):
    sleep_time = max(0, TIME_BETWEEN_RUNS - total_seconds(datetime.now() - start_run))
    print("Sleeping for %s seconds" % sleep_time)
    time.sleep(sleep_time)

def postNewVideos(db):
    """ Will post a new video if there are enough people on retainer"""
    ping_floor = unixtime(datetime.now() - timedelta(seconds = 10))
    
    sql = """SELECT logging.assignmentid, logging.servertime FROM logging, 
        (SELECT MAX(servertime) AS pingtime, assignmentid FROM logging WHERE servertime > %s AND event LIKE 'ping%%' GROUP BY assignmentid) as mostRecent 
    WHERE logging.servertime = mostRecent.pingTime AND logging.assignmentid=mostRecent.assignmentid AND event = 'ping-waiting' GROUP BY assignmentid"""
    result = db.query_and_return_array(sql, (ping_floor, ))
    num_waiting = len(result)

    print("%s on retainer right now" % num_waiting)
    
    if num_waiting >= MIN_ON_RETAINER:
        print("posting video")
        postVideo(db)


def postVideo(db):
    # get posted videos
    in_db = [row['filename'] for row in db.query_and_return_array("""SELECT filename FROM videos""")]

    dirList = os.listdir(VIDEO_DIRECTORY)
    in_directory = filter(lambda x: x.endswith('.3gp'), dirList)
    
    available_to_post = [item for item in in_directory if item[:-4] not in in_db]
    if len(available_to_post) > 0:
        encodeAndUpload(VIDEO_DIRECTORY + random.choice(available_to_post))
    else:  
        print("Nothing to post")

def encodeAndUpload(filename):
    (head, name, extension) = video_encoder.splitPath(filename)

    (width, height) = video_encoder.encodeVideo(head, name, extension)
    video_encoder.uploadVideo(name, width, height)


if __name__ == "__main__":
    if settings.SANDBOX:
        wait_bucket = 4 * 60
    else:
        wait_bucket = 4 * 60
    
    if MIN_ON_RETAINER < 3 and not settings.SANDBOX:
        raise Exception("Not enough people on retainer for non-sandbox tasks! Are you sure?")

    # Parse the options
    parser = OptionParser()
    parser.add_option("-n", "--number-of-hits", dest="number_of_hits", help="NUMBER of hits", metavar="NUMBER", default = 3)
    parser.add_option("-b", "--wait-bucket", dest="waitbucket", help="number of SECONDS to wait on retainer", metavar="SECONDS", default = wait_bucket)
    parser.add_option("-p", "--price", dest="price", help="number of CENTS to pay", metavar="CENTS", default = 4)
    parser.add_option("-x", "--expiration-time", dest="expiration", help="number of seconds before hit EXPIRES", metavar="EXPIRES", default = 10 * 60)
    
    print("TODO: clean up existing HITs")

    (options, args) = parser.parse_args()

    n = int(options.number_of_hits)
    b = int(options.waitbucket)
    p = int(options.price)/100.0
    x = int(options.expiration)

    quikTurKit(n, b, p, x)