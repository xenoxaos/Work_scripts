import re
import codecs
import email
import email.header
import email.mime.application as ponies
from email.mime.multipart import MIMEMultipart
import getpass
import imaplib
import locale
import mailbox
import math
import optparse
import re
import socket
import sys
import time
import unicodedata
import urllib
import os
import md5
import pickle
from optparse import OptionParser
from urlparse import urlparse

__version__ = "0.6"
#TODO: Possibly parse the .msf (Mork) files associated with Thunderbird to get folder names with invalid characters in them.
#TODO: Set size limit for email attachments (20MB) and remove or attempt to compress them and reattach as .zip/.xz


if sys.version_info < (2, 5):
    print >>sys.stderr, "MBOX Uploader requires Python 2.5 or later."
    sys.exit(1)

class MyOptionParser(OptionParser):
    def __init__(self):
        usage = "usage: python %prog [options]\n"\
                "  MBOX UNIX style mbox file.\n"\
                "  DEST is imap[s]://[USER[:PASSWORD]@]HOST[:PORT][/BOX]\n"\
                "  DEST has a priority over the options."
        OptionParser.__init__(self, usage,
                              version="UDel MBOX Uploader " + __version__)
        self.add_option("--user", help="login name [default: empty]")
        self.add_option("--password", help="login password")
        self.add_option("--logfile", help="Logfile name (w/o extension)")
        self.add_option("--path", help="Path to MBOX files [default: ./mbox")
        self.set_defaults(user = "",
                         password = "",
                         logfile = "MBOX_log",
                         path = ".\mbox")



    def parse_args(self, args):
        (options, args) = OptionParser.parse_args(self, args)
        return options


    def error(self, msg):
        raise optparse.OptParseError(self.get_usage() + "\n" + msg)


def si_prefix(n, prefixes=("", "k", "M", "G", "T", "P", "E", "Z", "Y"),
              block=1024, threshold=1):
    """Get SI prefix and reduced number."""
    if (n < block * threshold or len(prefixes) == 1):
        return (n, prefixes[0])
    return si_prefix(n / block, prefixes[1:])


def str_width(s):
    """Get string width."""
    w = 0
    for c in unicode(s):
        w += 1 + (unicodedata.east_asian_width(c) in "FWA")
    return w


def trim_width(s, width):
    """Get truncated string with specified width."""
    trimed = []
    for c in unicode(s):
        width -= str_width(c)
        if width <= 0:
            break
        trimed.append(c)
    return "".join(trimed)


def left_fit_width(s, width, fill=' '):
    """Make a string fixed width by padding or truncating.

    Note: fill can't be full width character.
    """
    s = trim_width(s, width)
    s += fill * (width - str_width(s))
    return s


class Progress():
    """Store and output progress information."""

    def __init__(self, total_count):
        self.total_count = total_count
        self.ok_count = 0
        self.count = 0
        self.format = "%" + str(len(str(total_count))) + "d/" + \
                      str(total_count) + " %5.1f %-2s  %s  "

    def begin(self, msg, f):
        """Called when start proccessing of a new message."""
        self.time_began = time.time()
        size, prefix = si_prefix(float(len(msg.as_string())), threshold=0.8)
        sbj = self.decode_subject(msg["subject"] or "")
        print >>sys.stderr, self.format % \
              (self.count + 1, size, prefix + "B", left_fit_width(sbj, 30)),
        print >>f, self.format % \
              (self.count + 1, size, prefix + "B", left_fit_width(sbj, 80)),

    def decode_subject(self, sbj):
        decoded = []
        try:
            parts = email.header.decode_header(sbj)

            for s, codec in parts:
                decoded.append(s.decode(codec or "ascii").encode('ascii'))
        except Exception, e:
            pass
        return "".join(decoded)

    def endOk(self, f):
        """Called when a message was processed successfully."""
        self.count += 1
        self.ok_count += 1
        print >>sys.stderr, "OK (%d sec)" % \
              math.ceil(time.time() - self.time_began)
        print >>f, "Email uploaded (%d sec)" % \
              math.ceil(time.time() - self.time_began)

    def endNg(self, err, f):
        """Called when an error has occurred while processing a message."""

        print >>sys.stderr, "NG (%s)" % err
        print >>f, "Email failed to upload: (%s)" % err

    def endAll(self, f):
        """Called when all message was processed."""
        print >>sys.stderr, "Done. (OK: %d, NG: %d)" % \
              (self.ok_count, self.total_count - self.ok_count)
        print >>f, "\nCurrent MBOX File Complete. Uploaded OK: %d, Upload Failed: %d)" % \
              (self.ok_count, self.total_count - self.ok_count)



def upload(imap, src, err, time_fields, f, message_digests, mbox_hash):
    print >>sys.stderr, \
          "Counting the mailbox (it could take a while for the large one)."

    p = Progress(len(src))
    for i, msg in src.iteritems():
        try:
            msg_hash = md5.md5(msg.as_string()).hexdigest()
            print md5.md5(msg.as_string()).hexdigest()


            p.begin(msg, f)
            #check if the hash combo already exists, if it is, don't reupload
            if ( mbox_hash + msg_hash in message_digests):
                print >>f,"message already uploaded"
                p.endNg("Already Uploaded",f)
                continue
            r, r2 = imap.upload(msg.get_delivery_time(time_fields),
                                msg.as_string(), 3)

            if r != "OK":
                raise Exception(r2[0]) # FIXME: Should use custom class
            p.endOk(f)
            message_digests.add( mbox_hash + msg_hash)
            continue
        except socket.error, e:
            p.endNg("Socket error: " + str(e), f)
        except Exception, e:
            p.endNg(e, f)
        if err is not None:
            err.add(msg)
    p.endAll(f)


def get_delivery_time(self, fields):
    """Extract delivery time from message.

    Try to extract the time data from given fields of message.
    The fields is a list and can consist of any of the following:
      * "from"      From_ line of mbox format.
      * "received"  The first "Received:" field in RFC 2822.
      * "date"      "Date:" field in RFC 2822.
    Return the current time if the fields is empty or no field
    had valid value.
    """
    def get_from_time(self):
        """Extract the time from From_ line."""
        time_str = self.get_from().split(" ", 1)[1]
        t = time_str.replace(",", " ").lower()
        t = re.sub(" (sun|mon|tue|wed|thu|fri|sat) ", " ",
                   " " + t + " ")
        if t.find(":") == -1:
            t += " 00:00:00"
        return t
    def get_received_time(self):
        """Extract the time from the first "Received:" field."""
        t = self["received"]
        t = t.split(";", 1)[1]
        t = t.lstrip()
        return t
    def get_date_time(self):
        """Extract the time from "Date:" field."""
        return self["date"]

    for field in fields:
        try:
            t = vars()["get_" + field + "_time"](self)
            t = email.utils.parsedate_tz(t)
            t = email.utils.mktime_tz(t)
            # Do not allow the time before 1970-01-01 because
            # some IMAP server (i.e. Gmail) ignore it, and
            # some MUA (Outlook Express?) set From_ date to
            # 1965-01-01 for all messages.
            if t < 0:
                continue
            return t
        except:
            pass
    # All failed. Return current time.
    return time.time()

# Directly attach get_delivery_time() to the mailbox.mboxMessage
# as a method.
# I want to use the factory parameter of mailbox.mbox()
# but it seems not to work in Python 2.5.4.
mailbox.mboxMessage.get_delivery_time = get_delivery_time


class IMAPUploader:
    def __init__(self, user, password):
        self.imap = None
        self.host = "imap.gmail.com"
        self.port = 993
        self.ssl = True
        self.box = ""
        self.user = user
        self.password = password
        self.retry = 3
        self.connectTime = time.time()
        self.mailbox_list = set()



    def upload(self, delivery_time, message, retry = None):
        if retry is None:
            retry = self.retry
        try:
            self.open()
            self.check_reconnect()
            self.imap.select(self.box)
            return self.imap.append(self.box, [], delivery_time, message)
        except (imaplib.IMAP4.abort, socket.error):
            self.close()
            if retry == 0:
                raise
        print >>sys.stderr, "(Reconnect)",
        time.sleep(5)
        return self.upload(delivery_time, message, retry - 1)

    def create_subfolder(self, folder_name):
        try:
            self.open()
            self.check_reconnect()
            (answer,status) = self.imap.select(folder_name)
            if answer == 'NO':
              try:
                self.imap.create(folder_name)
                self.get_mailbox()
                return True
              except:
                sys.exit(1)
            return False
        except (imaplib.IMAP4.abort, socket.error):
            self.close()

    def get_mailbox(self):
        #get a list of mailboxes that are currently on the IMAP server
        imap_list = self.imap.list()
        for item in imap_list[1]:
            item = re.split('" "',item)
            item = item[len(item)-1]
            item = item[:-1]
            self.mailbox_list.add(item)

    def mailbox_exist(self, mailbox):
        #if the mailbox exists on the server, return the name given by the
        #server to prevent any issues with mailbox Case
        for box in self.mailbox_list:
            if box.upper() == mailbox.upper():
                return (box, True)
        return (mailbox, False)

    def change_mailbox(self, mboxfile, log):
        special_mailboxes = {"Starred", "Important", "All Mail", "Drafts", "Trash", "Sent Mail"}
        mailbox_string = ""
        #split apart the mailbox and make sure that all parent mailboxes exist
        #or create the parent mailbox
        mailbox_parts =  mboxfile.split('/')
        for parts in mailbox_parts:
            #check for special mailboxes that exist in Gmail
            for special in special_mailboxes:
                if parts == special:
                    parts = "Uploaded_" + parts
                    break
            #Can't have a mailbox start with a space
            mailbox_string += parts.strip()
            #Cant have multiple spaces in a mailbox line
            mailbox_string = re.sub(' +', ' ', mailbox_string)

            #check if the wanted inbox exists already and if it does, store the
            #case that the server has, so Inbox => INBOX, etc
            #if it doesn't exist, create it
            (mailbox_string, exists) = self.mailbox_exist(mailbox_string)
            if exists == False:
                print "***Creating Subfolder: " + mailbox_string
                print >>log, "***Creating Subfolder: " + mailbox_string
                self.create_subfolder(mailbox_string)
            mailbox_string += "/"

        #This should always be the case, but just checking
        if mailbox_string.endswith("/"):
            mailbox_string = mailbox_string[:-1]

        self.box = mailbox_string
        print "***Changing to mailbox: %s"% mailbox_string
        print >>log, "Changing to mailbox: %s"% mailbox_string

    def open(self):
        if self.imap:
            return
        self.connectTime = time.time()
        imap_class = [imaplib.IMAP4, imaplib.IMAP4_SSL][self.ssl];
        self.imap = imap_class(self.host, self.port)
        self.imap.socket().settimeout(60)
        self.imap.login(self.user, self.password)
        self.get_mailbox()

    def close(self):
        if not self.imap:
            return
        self.imap.shutdown()
        self.imap = None

    def check_reconnect(self):
        #Having issues with HUGE mbox files (>2G) timing out.
        #If the connection has been up for longer than 15 min, reconnect
        if (time.time() - self.connectTime > 15*60):
            self.close()
            self.open()

def format_mailbox(subdirname, file, sourcedir):

    if subdirname.startswith(sourcedir):
        subdirname = subdirname[len(sourcedir)+1:]
    #Mozilla puts .sbd on directories, so we'll strip it out
    subdirname = subdirname.replace('.sbd', '')
    #convert backslashes to forward slashes for imap
    subdirname = subdirname.replace('\\', '/')
    subdirname += "/"
    subdirname += file
    #fix for having an '&' in the mailbox name
    subdirname = subdirname.replace('&', '&-')
    #The carat '^' is not allowed either
    subdirname = subdirname.replace('^', ' ')
    #Probably put an over abundance of these things at the beginning and end...
    if subdirname.startswith('/'):
        subdirname = subdirname[1:]
    if subdirname.endswith('/'):
        subdirname = subdirname[:-1]
    return subdirname

def main(args=None):
    try:
        # Setup locale
        # Set LC_TIME to "C" so that imaplib.Time2Internaldate()
        # uses English month name.
        locale.setlocale(locale.LC_ALL, "")
        locale.setlocale(locale.LC_TIME, "C")
        #  Encoding of the sys.stderr
        enc = locale.getlocale()[1] or "utf_8"
        sys.stderr = codecs.lookup(enc)[-1](sys.stderr, errors="ignore")

        # Parse arguments
        if args is None:
            args = sys.argv[1:]
        parser = MyOptionParser()
        options = parser.parse_args(args)
        if len(str(options.user)) == 0:
            print "User name: ",
            options.user = sys.stdin.readline().rstrip("\n")
        if len(str(options.password)) == 0:
            options.password = getpass.getpass()

        sourcedir = options.path
        logname = options.logfile +".txt"

        logfile = open(logname, 'a')
        #Try to read filenames from completed.log for files we can skip
        completed_items = [""]
        try:
            completed_mbox = open("completed.log", 'r')

            for line in completed_mbox:
                completed_items.append(line.strip())
            completed_mbox.close()
        except:
            print "No previous logs"
        completed_mbox = open("completed.log", 'a')

        errname = options.logfile + "_failed_messages.mbox"

        usern = options.user
        passwordn = options.password


        time_fields=["from", "received", "date"]
        start_time = time.time()
        #send current time in epoch format
        print >>logfile, start_time

        print >>sys.stderr,"Connecting to IMAP Server as %s" % usern
        print >>logfile,'Connecting to IMAP Server as %s'% usern

        boxnames = dict()

        #get the set that's been pickled already for uploaded individual messages.
        message_digests = set()
        try:
            with open('message_hash.bin', 'rb') as input:
                message_digests = pickle.load(input)
        except:
            print "no previous message data"

        # Connect to the server and login
        uploader = IMAPUploader(usern, passwordn)
        uploader.open()
        for stuff in uploader.mailbox_list:
            print stuff

        try:
            os.mkdir("Failed Messages")
        except:
            print "Failed Messages directory already exists"
        for r,d,files in os.walk(sourcedir):
             for file in files:
                #open the current file as a mbox file
                sourcefile = os.path.join(r,file)
                src = mailbox.mbox(sourcefile, create=False)

                #check if the mbox file has no messages and skip it if true
                if len(src) is 0:
                    continue

                #Get the foldername that corresponds to the current mbox file
                #Change to that mailbox on the IMAP server and create it if
                #it doesnt exist
                folderName = format_mailbox(r, file, sourcedir)
                uploader.change_mailbox(folderName, logfile)

                #add message count to the dict
                boxnames[sourcefile] = len(src)

                #Create a mbox file for rejected mail messages for review later
                err = mailbox.mbox(os.path.join("Failed Messages", folderName.replace("/", "_") + "_" + errname))

                # Upload
                print >>logfile, "Uploading messages in file %s\n"% sourcefile
                print >>sys.stderr, "Uploading " + file

                #hash the name of the mbox file+path
                mbox_hash = md5.md5(sourcefile).hexdigest()

                upload(uploader, src, err, time_fields, logfile, message_digests, mbox_hash)

                #If nothing went into the err mbox file, delete it.
                if len(err) is 0:
                    err.close()
                    os.remove(os.path.join("Failed Messages", folderName.replace("/", "_") + "_" + errname))
                print >>logfile, "\n"

                #write the completed filename to completed.log for resume purposes
                print >>completed_mbox, sourcefile


        #write a summary of mailboxes and message counts
        for box in boxnames:
            print >>logfile, "%s: %s messages"% (box, boxnames[box])
        print "\n\n\n\nMail transfer is now complete. You may close this window now.\n\n\n"
        print >>logfile, time.time()

        m, s = divmod(time.time() - start_time, 60)
        h, m = divmod(m, 60)

        print >>logfile, "%d:%02d:%02d" % (h, m, s)
        with open('message_hash.bin', 'wb') as output:
            pickle.dump(message_digests, output, pickle.HIGHEST_PROTOCOL)
        return 0
    except optparse.OptParseError, e:
        print >>sys.stderr, e
        return 2
    except mailbox.NoSuchMailboxError, e:
        print >>sys.stderr, "No such mailbox:", e
        return 1
    except socket.timeout, e:
        print >>sys.stderr, "Timed out"
        return 1
    except imaplib.IMAP4.error, e:
        print >>sys.stderr, "IMAP4 error:", e
        return 1
    except KeyboardInterrupt, e:
        print >>sys.stderr, "Interrupted"
        return 130
    except Exception, e:
        print >>sys.stderr, "An unknown error has occurred: ", e
        return 1


if __name__ == "__main__":
    sys.exit(main())
