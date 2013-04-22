#! /usr/bin/perl
    use strict;
    use warnings;
    use Net::SNMP;
    
    #for using mysql
    use DBI;

    my $dbUser = "USERNAME";
    my $dbPass = "PASSWORD";
    my $dbh = DBI->connect('dbi:mysql:printer_stats', $dbUser, $dbPass);

    ##Set up current time to use as a unique DB entry,
    ##get time and prune off anything that's after it
    my $currentHour = time();
    $currentHour = $currentHour - $currentHour % 3600;
    
    #OID for string containing printer type, hp4700, hp9050, etc.
    #so far this OID is the same across models and brands
    my $OID_hrDeviceDescr = '1.3.6.1.2.1.25.3.2.1.3.1';


    #OID to determine which printer is which, Unique to each printer
    #SMDC_1 SMDC_2 SMDC_3 SMDC_C PHYS_1 RSRV_1 REFR_1 REFR_2
    #INFO_1 INFO_2 AGRC_1 ATCP_1
    ##These ID's are being stored in sysLocation 
    #TODO: Change using sysLocation as ID to using Serial Number, then
    #use a manually modified table to match the SN to Printer Group, and Shortname

    my $OID_sysLocation = '1.3.6.1.2.1.1.6.0';

    ##future serial number OID
    #my $OID_serialNumber = '1.3.6.1.2.1.43.5.1.1.17.1';
    ##oid for dell sn
   ## .1.3.6.1.4.1.641.2.1.2.1.6.1
    ##I'm not sure if this works on any other printers, but on a 9050 it does.
    #my $OID_frontDisplayPanel = '1.3.6.1.2.1.43.16.5.1.2.1.1';

    #Current list of IPs and current shortnames, shortnames will soon be ignored.
   my @ipAddresses = ("127.0.0.1");



    #setting up OIDs lookup table for different models
    #We need different information from different models.

    #the printerID is used for DB selection, soon will change to SN

    my %hp9050 =       ("duplexLetterCount",            '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.3.2.0',
                        "simplexLetterCount",           '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.1.2.0',
                        "totalLetterCount",             '1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.8.5.1.2.0',
   #                     "duplex1Image",                 '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.10.2.0',
                        "printerID",                    '1.3.6.1.2.1.1.6.0');
    
    my %hp4350 =       ("totalLetterCount",             '1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.8.5.1.2.0',
                        "simplexLetterCount",           '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.1.2.0',
                        "duplexLetterCount",            '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.3.2.0',
    #                    "duplex1Image",                 '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.10.2.0',
                        "printerID",                    '1.3.6.1.2.1.1.6.0');
    
    my %hp4700 =       ("totalLetterCount",             '1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.8.5.1.2.0',
                        "printerID",                    '1.3.6.1.2.1.1.6.0',
                        "simplexLetterMono",            '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.1.2.0',
                        "simplexLetterColor",           '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.3.1.1.2.0',
                        "duplexLetterMono",             '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.1.1.3.2.0',
                        "duplexLetterColor",            '1.3.6.1.4.1.11.2.3.9.4.2.1.1.16.3.1.3.2.0');
    
    my %xerox3250 =    ("totalLetterCount",             '1.3.6.1.2.1.43.10.2.1.4.1.1',
                        "printerID",                    '1.3.6.1.2.1.1.6.0');
    
    my %dell5530dn =   ("totalLetterCount",             '1.3.6.1.4.1.641.2.1.5.2.0',
                        "printerID",                    '1.3.6.1.2.1.1.6.0');
    

    #Using the data from this, it will see if the quoted text in the %modelNumbers
    #hash is contained in the value returned and then set the %OIDPointer hash
    #to the hash containing the list of OIDs for that model printer


    my %OIDPointer;
    my %modelNumbers = ('9050', \%hp9050,
                        '4350', \%hp4350,
                        '4700', \%hp4700,
                        '3250', \%xerox3250,
                        '5530', \%dell5530dn);



foreach my $printerIP (@ipAddresses){ #runs through list of each IP
    
    #For each IP, start new SNMP session on fail, skip to next IP
    my ($SNMPsession, $error) = Net::SNMP->session(
                            -hostname  => shift || $printerIP,
                            -community => shift || 'public',
                            );
    
    if (!defined $SNMPsession){
    printf "ERROR: %s.\n", $error;
    next;
    }
    #If IP is not responding, go to next printer
    #possibly add in code to check the DB and insert NULL data for the current time.

    my $printerType = $SNMPsession->get_request(-varbindlist => [$OID_hrDeviceDescr],);
    if (!defined $printerType){
	print "Printer at IP: " . $printerIP . " is not responding.\n\n";
	next;
	}




    ##Check to see what kind of printer the printer at current IP is to
    ##lookup what information we need to pull from specific model
    foreach my $type (%modelNumbers){
        if ($printerType->{$OID_hrDeviceDescr}=~/$type/)
            {
            %OIDPointer =  %{$modelNumbers{$type}};
            last;
            }
    }#end foreach my $type 

    ##Generate list of OIDs that need scraped from the printer dependent on what kind of printer
    my @OIDList = ();
    foreach my $OID (keys %OIDPointer){
        push(@OIDList, $OIDPointer{$OID});   
    }
    
    ##Second request to printer to ask for relevant data. 
    ##checking to see if printer is up/down not needed here because it should have skipped this
    my $SNMPresult = $SNMPsession->get_request(-varbindlist => [ @OIDList ],);
 
    #Reseting SQL query for new printer, even though it should be clear now, but just to be safe
    my $statement = '';
    my $columns = '';
    my $data = '';
    my $printerID;

    foreach my $key (keys %OIDPointer){
        ##we don't need to store the printerID/Serial because that's the DB name.
        if($key=~/printerID/){
            $printerID = $SNMPresult->{$OIDPointer{$key}};
            next;        
        }
        ##tack on the column name and data with their commas, we'll prune the last off later
        $columns .= $key;
        $columns .= ", ";
        $data .= $SNMPresult->{$OIDPointer{$key}};
        $data .= ", ";
        
    }
    ##add the current epoch to the insert statment, current time is %3600 to clean up the time to make 
analysis later cleaner
    $columns .= "epoch";
    $data .= $currentHour;
    ##trim off the trailing ", " from the SQL statement
    $columns =~s/, $//;
    $data =~s/, $//;
    print $printerID . "\n" . $columns . "\n" . $data . "\n";
    $statement = 'INSERT INTO ' .  $printerID . '(' . $columns . ') VALUES (' . $data . ')';
    ##submit data to current DB into the appropriate table
    
    ###*******************
    #TODO: create a check to see if table in DB exists, if not, create one with columns for each
    #datapoint, as well as id(autoincrement) and epoch/datetime
    #that way it makes it really easy to add a new printer, then for the public printers put a
    #lookup table in the DB that has SN->location/printername

    my $sth = $dbh->prepare($statement);
    $sth->execute;
    printf("\n");
    ##Close current SNMP session to prepare for new one
    $SNMPsession->close();
}#end foreach my $printerIP (@ipAddresses)

