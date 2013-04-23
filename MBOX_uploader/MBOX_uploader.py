import codecs
import email
import email.header
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
from optparse import OptionParser
from urlparse import urlparse

__version__ = "0.1"

if sys.version_info < (2, 5):
    print >>sys.stderr, "UDel MBOX Uploader requires Python 2.5 or later."
    sys.exit(1)

class MyOptionParser(OptionParser):
    def __init__(self):
        usage = "usage: python %prog [options]\n"\
                "  Utility to upload multiple Thunderbird/*nix style MBOX files\n"\
        OptionParser.__init__(self, usage,
                              version="UDel MBOX Uploader " + __version__)
        self.add_option("--user", help="login name [default: empty]")
        self.add_option("--password", help="login password")
        self.add_option("--logfile", help="Logfile name (w/o extension)")
        self.add_option("--path", help="Path to MBOX files [default: ./mbox")
        self.set_defaults(user = "",
                         password = "",
                         logfile = "MBOX_log.txt",
                         path = "./mbox")



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
                decoded.append(s.decode(codec or "ascii"))
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



def upload(imap, src, err, time_fields, f):
    print >>sys.stderr, \
          "Counting the mailbox (it could take a while for the large one)."
    p = Progress(len(src))
    for i, msg in src.iteritems():
        try:
            p.begin(msg, f)
            r, r2 = imap.upload(msg.get_delivery_time(time_fields),
                                msg.as_string(), 3)
            if r != "OK":
                raise Exception(r2[0])
            p.endOk(f)
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



    def upload(self, delivery_time, message, retry = None):
        if retry is None:
            retry = self.retry
        try:
            self.open()
            (answer,status) = self.imap.select(self.box)
            if answer == 'NO':
              try:
                self.imap.create(self.box)
              except:
                sys.exit(1)
	    return self.imap.append(self.box, [], delivery_time, message)
        except (imaplib.IMAP4.abort, socket.error):
            self.close()
            if retry == 0:
                raise
        print >>sys.stderr, "(Reconnect)",
        time.sleep(5)
        return self.upload(delivery_time, message, retry - 1)

    def change_mailbox(self, mboxfile):
        self.box = mboxfile

    def open(self):
        if self.imap:
            return
        imap_class = [imaplib.IMAP4, imaplib.IMAP4_SSL][self.ssl];
        self.imap = imap_class(self.host, self.port)
        self.imap.socket().settimeout(60)
        self.imap.login(self.user, self.password)

    def close(self):
        if not self.imap:
            return
        self.imap.shutdown()
        self.imap = None


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
        #options = options.__dict__
        sourcedir = options.path
        logname = options.logfile +".txt"
        logfile = open(logname, 'w')
        err = logfile + "_failed_messages.mbox"
        usern = options.user
        passwordn = options.password
        time_fields=["from", "received", "date"]
        # Connect to the server and login
        print >>sys.stderr, \
              "Connecting to IMAP Server as %s" % usern
        print >>logfile,'Connecting to IMAP Server as %s'% usern

        uploader = IMAPUploader(usern, passwordn)
        uploader.open()
        totalMessages = 0
        totalMBOXFiles = 0
        print >>logfile, "List of MBOX files and message Counts:"
        for r,d,files in os.walk(sourcedir):
            for file in files:
                totalMBOXFiles +=1
                thisMBOXMessages = 0
                sourcefile = os.path.join(r,file)
                mboxfile = mailbox.mbox(sourcefile, create=False)
                for message in mboxfile:
                    totalMessages +=1
                    thisMBOXMessages +=1
                print >>logfile, 'MBOX: %s %d'% (left_fit_width(file + ":",80, ' '), thisMBOXMessages)
        print >>logfile, "\n"
        print >>logfile, 'Total MBOX Files: %d'% totalMBOXFiles
        print >>logfile, 'Total Messages: %d'% totalMessages
        print >>logfile, "\n"


        for r,d,files in os.walk(sourcedir):
            for file in files:
                uploader.change_mailbox(file)
                print "mailboxname:" + file
                sourcefile = os.path.join(r,file)
                src = mailbox.mbox(sourcefile, create=False)
                if err:
                    err = mailbox.mbox(err)
                # Upload
                print >>logfile, "Uploading messages in file %s\n"% file
                print >>sys.stderr, "Uploading..." + file
                upload(uploader, src, err, time_fields, logfile)
                print >>logfile, "\n"
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
