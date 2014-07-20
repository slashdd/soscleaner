# Copyright (C) 2013  Jamie Duncan (jduncan@redhat.com)

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# File Name : sos-gov.py
# Creation Date : 10-01-2013
# Created By : Jamie Duncan
# Last Modified : Sat 19 Jul 2014 11:30:16 PM EDT
# Purpose : an sosreport scrubber

import os
import re
import errno
import sys
import magic
import uuid
import shutil
import struct, socket
import tempfile
import logging
import tarfile

class SOSCleaner:
    '''
    A class to parse through an sosreport and begin the cleaning process required in many industries
    Parameters:
    debug - will generate add'l output to STDOUT. defaults to no
    reporting - will post progress and overall statistics to STDOUT. defaults to yes
    '''
    def __init__(self, quiet=False):

        self.name = 'soscleaner'
        self.version = '0.1'
        self.loglevel = 'INFO' #this can be overridden by the command-line app
        self.quiet = quiet

        #IP obfuscation information
        self.ip_db = dict() #IP database
        self.start_ip = '10.230.230.1'

        #Hostname obfuscation information
        self.hn_db = dict() #hostname database
        self.hostname_count = 0

        #Domainname obfuscation information
        self.dn_db = dict() #domainname database
        self.root_domain = 'example.com' #right now this needs to be a 2nd level domain, like foo.com, example.com, domain.org, etc.
        self.origin_path, self.dir_path, self.session, self.logfile, self.uuid = self._prep_environment()
        self._start_logging(self.logfile)

        self.has_sosreport = True
        self.magic = magic.open(magic.MAGIC_NONE)
        self.magic.load()

    def _check_uid(self): # pragma no cover
        if os.getuid() != 0:
            raise Exception("You Must Execute soscleaner As Root")

    def _skip_file(self, d, files):
        '''
        The function passed into shutil.copytree to ignore certain patterns and filetypes
        Currently Skipped
        Directories - handled by copytree
        Symlinks - handled by copytree
        Write-only files (stuff in /proc)
        Binaries (can't scan them)
        '''
        skip_list = []
        for f in files:
            f_full = os.path.join(d, f)
            if not os.path.isdir(f_full):
                if not os.path.islink(f_full):
                    #mode = oct(os.stat(f_full).st_mode)[-3:]
                    # executing as root makes this first if clause useless.
                    # i thought i'd already removed it. - jduncan
                    #if mode == '200' or mode == '444' or mode == '400':
                    #    skip_list.append(f)
                    if 'text' not in self.magic.file(f_full):
                        skip_list.append(f)

        return skip_list

    def _start_logging(self, filename):
        #will get the logging instance going
        loglevel_config = 'logging.%s' % self.loglevel

        #i'd like the stdout to be under another logging name than 'con_out'
        console_log_level = 25  #between INFO and WARNING
        logging.addLevelName(console_log_level, "CONSOLE")

        def con_out(self, message, *args, **kws):
            self._log(console_log_level, message, args, **kws)

        logging.Logger.con_out = con_out

        logging.basicConfig(filename=filename,
            level=eval(loglevel_config),
            format='%(asctime)s %(name)s %(levelname)s: %(message)s',
            datefmt = '%m-%d %H:%M:%S'
            )
        if not self.quiet: # pragma: no cover
            console = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s', '%m-%d %H:%M:%S')
            console.setFormatter(formatter)
            console.setLevel(console_log_level)
	self.logger = logging.getLogger(__name__)
        if not self.quiet:
            self.logger.addHandler(console) # pragma: no cover

        self.logger.con_out("Log File Created at %s" % filename)

    def _prep_environment(self):

        #we set up our various needed directory structures, etc.
        uuid = str(uuid.uuid4().int)[:16]                       # 16 digit random string
        origin_path = "/tmp/soscleaner-origin-%s" % uuid        # the origin dir we'll copy the files into
        dir_path = "/tmp/soscleaner-%s" % uuid                  # the dir we will put our cleaned files into
        session = "soscleaner-%s" % uuid                        # short-hand for the soscleaner session to create reports, etc.
        logfile = "/tmp/%s.log" % session                       # the primary logfile

        return origin_path, dir_path, session, logfile, uuid

    def _extract_sosreport(self, path):

        self.logger.con_out("Beginning SOSReport Extraction")
        compression_sig = self.magic.file(path).lower()
        if 'directory' in compression_sig:
            self.logger.info('%s appears to be a %s - continuing', path, compression_sig)
            return path

        elif 'compressed data' in compression_sig:
            if compression_sig == 'xz compressed data':
                #This is a hack to account for the fact that the tarfile library doesn't
                #handle lzma (XZ) compression until version 3.3 beta
                try:
                    self.logger.info('Data Source Appears To Be LZMA Encrypted Data - decompressing into %s', self.origin_path)
                    self.logger.info('LZMA Hack - Creating %s', self.origin_path)
                    os.system('mkdir %s' % self.origin_path)
                    os.system('tar -xJf %s -C %s' % (path, self.origin_path))
                    return_path = os.path.join(self.origin_path, os.listdir(self.origin_path)[0])

                    return return_path

                except Exception,e: # pragma: no cover
                    self.logger.exception(e)
                    raise Exception('DecompressionError, Unable to decrypt LZMA compressed file %s', path)

            else:
                p = tarfile.open(path, 'r')

                self.logger.info('Data Source Appears To Be %s - decompressing into %s', compression_sig, self.origin_path)
                try:
                    p.extractall(self.origin_path)
                    return_path = os.path.join(self.origin_path, os.path.commonprefix(p.getnames()))

                    return return_path

                except Exception, e:    # pragma: no cover
                    self.logger.exception(e)
                    raise Exception("DeCompressionError: Unable to De-Compress %s into %s", path, self.origin_path)
        else:   # pragma: no cover
            raise Exception('CompressionError: Unable To Determine Compression Type')

    def _sub_ip(self, line):
        '''
        This will substitute an obfuscated IP for each instance of a given IP in a file
        This is called in the self._clean_line function, along with user _sub_* functions to scrub a given
        line in a file.
        It scans a given line and if an IP exists, it obfuscates the IP using _ip2db and returns the altered line
        '''
        try:
            pattern = r"(((\b25[0-5]|\b2[0-4][0-9]|\b1[0-9][0-9]|\b[1-9][0-9]|\b[1-9]))(\.(\b25[0-5]|\b2[0-4][0-9]|\b1[0-9][0-9]|\b[1-9][0-9]|\b[0-9])){3})"
            ips = [each[0] for each in re.findall(pattern, line)]
            if len(ips) > 0:
                for ip in ips:
                    new_ip = self._ip2db(ip)
                    self.logger.debug("Obfuscating IP - %s > %s", ip, new_ip)
                    line = line.replace(ip, new_ip)
            return line
        except Exception,e: # pragma: no cover
            self.logger.exception(e)
            raise Exception('SubIPError: Unable to Substitute IP Address - %s', ip)

    def _get_disclaimer(self):  # pragma: no cover
        #prints a disclaimer that this isn't an excuse for manual or any other sort of data verification

        self.logger.con_out("%s version %s" % (self.name, self.version))
        self.logger.warning("%s is a tool to help obfuscate sensitive information from an existing sosreport." % self.name)
        self.logger.warning("Please review the content before passing it along to any third party.")

    def _create_ip_report(self):
        '''
        this will take the obfuscated ip and hostname databases and output csv files
        '''
        try:
            ip_report_name = "/tmp/%s-ip.csv" % self.session
            self.logger.con_out('Creating IP Report - %s', ip_report_name)
            ip_report = open(ip_report_name, 'w')
            ip_report.write('Obfuscated IP,Original IP\n')
            for k,v in self.ip_db.items():
                ip_report.write('%s,%s\n' %(self._int2ip(k),self._int2ip(v)))
            ip_report.close()
            self.logger.info('Completed IP Report')

            self.ip_report = ip_report_name
        except Exception,e: # pragma: no cover
            self.logger.exception(e)
            raise Exception('CreateReport Error: Error Creating IP Report')

    def _create_hn_report(self):
        if self.process_hostnames:
            try:
                hn_report_name = "/tmp/%s-hostname.csv" % self.session
                self.logger.con_out('Creating Hostname Report - %s', hn_report_name)
                hn_report = open(hn_report_name, 'w')
                hn_report.write('Obfuscated Hostname,Original Hostname\n')
                for k,v in self.hn_db.items():
                    hn_report.write('%s,%s\n' %(k,v))
                hn_report.close()
                self.logger.info('Completed Hostname Report')

                self.hn_report = hn_report_name
            except Exception,e: #pragma: no cover
                self.logger.exception(e)
                raise Exception('CreateReport Error: Error Creating Hostname Report')
        else:
            self.logger.warning('Hostname Report Not Generated - Unable to determine hostname')
            self.hn_report = None

    def _create_dn_report(self):
        if self.domain_count >= 1:
            try:
                dn_report_name = "/tmp/%s-dn.csv" % self.session
                self.logger.con_out('Creating Domainname Report - %s', dn_report_name)
                dn_report = open(dn_report_name, 'w')
                dn_report.write('Obfuscated Domain,Original Domain\n')
                for k,v in self.dn_db.items():
                    dn_report.write('%s,%s\n' %(k,v))
                dn_report.close()
                self.logger.info('Completed Domainname Report')

                self.dn_report = dn_report_name

            except Exception, e: # pragma: no cover
                self.logger.exception(e)
                raise Exception('CreateReport Error: Error Creating Domainname Report')

    def _create_reports(self): # pragma: no cover

        self._create_ip_report()
        self._create_hn_report()
        self._create_dn_report()

    def _sub_hostname(self, line):
        '''
        This will replace the exact hostname and all instances of the domain name with the obfuscated alternatives.
        Example:
        '''
        try:
            for od,d in self.dn_db.items():
                #regex = re.compile(r'\w*\.%s' % d)
                regex = re.compile(r'(?![\W\-\:\ \.])[a-zA-Z0-9\-\_\.]*\.%s' % d)
                hostnames = [each for each in regex.findall(line)]
                if len(hostnames) > 0:
                    for hn in hostnames:
                        new_hn = self._hn2db(hn)
                        self.logger.debug("Obfuscating FQDN - %s > %s", hn, new_hn)
                        line = line.replace(hn, new_hn)
            line = line.replace(self.hostname, self._hn2db(self.hostname))  #catch any non-fqdn instances of the system hostname

            return line
        except Exception,e: # pragma: no cover
            self.logger.exception(e)
            raise Exception('SubHostnameError: Unable to Substitute Hostname/Domainname')

    def _make_dest_env(self):
        '''
        This will create the folder in /tmp to store the sanitized files and populate it using shutil
        These are the files that will be scrubbed
        '''
        try:
            if self.has_sosreport:
                shutil.copytree(self.report, self.dir_path, symlinks=True, ignore=self._skip_file)
            else:
                #we don't have an sosreport, and we've just copied the specified files into origin_path, so we'll copy that.
                shutil.copytree(self.origin_path, self.dir_path, symlinks=True, ignore=self._skip_file)

        except Exception, e:    #pragma: no cover
            self.logger.exception(e)
            raise Exception("DestinationEnvironment Error: Cannot Create Destination Environment")

    def _create_archive(self):
        '''This will create a tar.gz compressed archive of the scrubbed directory'''
        try:
            self.archive_path = "/tmp/%s.tar.gz" % self.session
            self.logger.con_out('Creating SOSCleaner Archive - %s', self.archive_path)
            t = tarfile.open(self.archive_path, 'w:gz')
            for dirpath, dirnames, filenames in os.walk(self.dir_path):
                for f in filenames:
                    f_full = os.path.join(dirpath, f)
                    f_archive = f_full.replace('/tmp','')
                    self.logger.debug('adding %s to %s archive', f_archive, self.archive_path)
                    t.add(f_full, arcname=f_archive)
        except Exception,e: #pragma: no cover
            self.logger.exception(e)
            raise Exception('CreateArchiveError: Unable to create Archive')

        self._clean_up()
        self.logger.info('Archiving Complete')
        self.logger.con_out('SOSCleaner Complete')
        t.add(self.logfile, arcname=self.logfile.replace('/tmp',''))
        t.close()

    def _clean_up(self):
        '''This will clean up origin directories, etc.'''
        self.logger.info('Beginning Clean Up Process')
        try:
            if self.origin_path:
                self.logger.info('Removing Origin Directory - %s', self.origin_path)
                shutil.rmtree(self.origin_path)
            self.logger.info('Removing Working Directory - %s', self.dir_path)
            shutil.rmtree(self.dir_path)
            self.logger.info('Clean Up Process Complete')
        except Exception, e:    #pragma: no cover
            self.logger.exception(e)

    def _domains2db(self):
        #adds any additional domainnames to the domain database to be searched for
        try:
            #we will add the root domain for an FQDN as well.
            if self.domainname is not None:
                self.dn_db[self.root_domain] = self.domainname
                self.logger.con_out("Obfuscated Domain Created - %s" % self.root_domain)

            split_root_d = self.root_domain.split('.')

            for d in self.domains:
                if d not in self.dn_db.values(): #no duplicates
                    d_number = len(self.dn_db)
                    o_domain = "%s%s.%s" % (split_root_d[0], d_number, split_root_d[1])
                    self.dn_db[o_domain] = d
                    self.logger.con_out("Obfuscated Domain Created - %s" % o_domain)

            self.domain_count = len(self.dn_db)
            return True

        except Exception, e: # pragma: no cover
            self.logger.exception(e)

    def _get_hostname(self):
        #gets the hostname and stores hostname/domainname so they can be filtered out later

        try:
            self.process_hostnames = True
            hostfile = os.path.join(self.dir_path, 'hostname')
            fh = open(hostfile, 'r')
            name_list = fh.readline().rstrip().split('.')

            hostname = name_list[0]
            if len(name_list) > 1:
                domainname = '.'.join(name_list[1:len(name_list)])
            else:
                domainname = None

            return hostname, domainname

        except IOError, e: #the 'hostname' file doesn't exist or isn't readable for some reason
            self.process_hostnames = False
            self.logger.warning("Unable to determine system hostname!!!")
            self.logger.warning("Hostname Data Obfuscation Will Not Occur!!!")
            self.logger.warning("To Remedy This Situation please enable the 'general' plugin when running sosreport")
            self.logger.warning("and/or be sure the 'hostname' symlink exists in the root directory of you sosreport")
            self.logger.exception(e)

            hostname = 'unknown'
            domainname = 'unknown'

            return hostname, domainname

        except Exception, e: # pragma: no cover
            self.logger.exception(e)
            raise Exception('GetHostname Error: Cannot resolve hostname from %s') % hostfile

    def _ip2int(self, ipstr):
        #converts a dotted decimal IP address into an integer that can be incremented
        integer = struct.unpack('!I', socket.inet_aton(ipstr))[0]

        return integer

    def _int2ip(self, num):
        #converts an integer stored in the IP database into a dotted decimal IP
        ip = socket.inet_ntoa(struct.pack('!I', num))

        return ip

    def _ip2db(self, ip):
        '''
        adds an IP address to the IP database and returns the obfuscated entry, or returns the
        existing obfuscated IP entry
        FORMAT:
        {$obfuscated_ip: $original_ip,}
        '''

        ip_num = self._ip2int(ip)
        ip_found = False
        db = self.ip_db
        for k,v in db.iteritems():
            if v == ip_num:
                ret_ip = self._int2ip(k)
                ip_found = True
        if ip_found:                #the entry already existed
            return ret_ip
        else:                       #the entry did not already exist
            if len(self.ip_db) > 0:
                new_ip = max(db.keys()) + 1
            else:
                new_ip = self._ip2int(self.start_ip)
            db[new_ip] = ip_num

            return self._int2ip(new_ip)

    def _hn2db(self, hn):
        '''
        This will add a hostname for a hostname for an included domain or return an existing entry
        '''
        db = self.hn_db
        hn_found = False
        for k,v in db.iteritems():
            if v == hn:  #the hostname is in the database
                ret_hn = k
                hn_found = True
        if hn_found:
            return ret_hn
        else:
            self.hostname_count += 1    #we have a new hostname, so we increment the counter to get the host ID number
            o_domain = self.root_domain
            for od,d in self.dn_db.items():
                if d in hn:
                    o_domain = od
            new_hn = "host%s.%s" % (self.hostname_count, o_domain)
            self.hn_db[new_hn] = hn

            return new_hn

    def _walk_report(self, folder):
        '''returns a dictonary of dictionaries in the format {directory_name:[file1,file2,filex]}'''

        dir_list = {}
        try:
            for dirName, subdirList, fileList in os.walk(folder):
                x = []
                for fname in fileList:
                    x.append(fname)
                dir_list[dirName] = x

            return dir_list
        except Exception, e: # pragma: no cover
            self.logger.exception(e)
            raise Exception("WalkReport Error: Unable to Walk Report")

    def _file_list(self, folder):
        '''returns a list of file names in an sosreport directory'''
        rtn = []
        walk = self._walk_report(folder)
        for key,val in walk.items():
            for v in val:
                x=os.path.join(key,v)
                rtn.append(x)

        self.file_count = len(rtn)  #a count of the files we'll have in the final cleaned sosreport, for reporting
        return rtn

    def _clean_line(self, l):
        '''this will return a line with obfuscations for all possible variables, hostname, ip, etc.'''

        new_line = self._sub_ip(l)  #IP substitution
        if self.process_hostnames:
            new_line = self._sub_hostname(new_line)    #Hostname substitution

        return new_line

    def _clean_file(self, f):
        '''this will take a given file path, scrub it accordingly, and save a new copy of the file
        in the same location'''
        if os.path.exists(f) and not os.path.islink(f):
            tmp_file = tempfile.TemporaryFile()
            try:
                fh = open(f,'r')
                data = fh.readlines()
                fh.close()
                if len(data) > 0: #if the file isn't empty:
                    for l in data:
                        new_l = self._clean_line(l)
                        tmp_file.write(new_l)

                    tmp_file.seek(0)

            except Exception, e: # pragma: no cover
                self.logger.exception(e)
                raise Exception("CleanFile Error: Cannot Open File For Reading - %s" % f)

            try:
                if len(data) > 0:
                    new_fh = open(f, 'w')
                    for line in tmp_file:
                        new_fh.write(line)
                    new_fh.close()
            except Exception, e: # pragma: no cover
                self.logger.exception(e)
                raise Exception("CleanFile Error: Cannot Write to New File - %s" % f)

            finally:
                tmp_file.close()

    def _add_extra_files(self, files):
        '''if extra files are to be analyzed with an sosreport, this will add them to the origin path to be analyzed'''

        try:
            for f in files:
                self.logger.con_out("adding additional file for analysis: %s"  % f)
                fname = os.path.basename(f)
                f_new = os.path.join(self.origin_path, fname)
                shutil.copyfile(f,f_new)
        except IOError, e:
            self.logger.con_out("ExtraFileError: %s is not readable or does not exist. Skipping File" % f)
            self.logger.exception(e)
            pass
        except Exception, e:    # pragma: no cover
            self.logger.exception(e)
            raise Exception("ExtraFileError: Unable to Process Extra File - %s" % f)

    def _clean_files_only(self, files):
        ''' if a user only wants to process one or more specific files, instead of a full sosreport '''
        try:
            os.makedirs(self.origin_path)    # create the origin directory
            self._add_extra_files(files)
            self.has_sosreport = False

        except OSError, e:
            if exception.errno != errno.EEXIST:
                raise
        except Exception, e:    # pragma: no cover
            self.logger.exception(e)
            raise Exception("CleanFilesOnlyError: unable to process")

    def clean_report(self, options, sosreport): # pragma: no cover
        '''this is the primary function, to put everything together and analyze an sosreport'''

        self._check_uid() #make sure it's soscleaner is running as root
        self._get_disclaimer()
        self.domains = options.domains
        if options.files and sosreport == None: #files to process, but no sosreport
            self._clean_files_only(options.files)
        else:
            self.report = self._extract_sosreport(sosreport)
            if not self.hostname == 'unknown':
                self.hn_db['host0'] = self.hostname     #we'll prime the hostname pump to clear out a ton of useless logic later
        self._make_dest_env()   #create the working directory
        self.hostname, self.domainname = self._get_hostname()
        self._domains2db()
        if options.files and self.has_sosreport:
            self._add_extra_files(options.files)
        sosreport_files = self._file_list(self.dir_path)
        self.logger.con_out("IP Obfuscation Start Address - %s", self.start_ip)
        self.logger.con_out("*** SOSCleaner Processing ***")
        self.logger.info("Working Directory - %s", self.dir_path)
        for f in sosreport_files:
            self.logger.debug("Cleaning %s", f)
            self._clean_file(f)
        self.logger.con_out("*** SOSCleaner Statistics ***")
        self.logger.con_out("IP Addresses Obfuscated - %s", len(self.ip_db))
        self.logger.con_out("Hostnames Obfuscated - %s" , len(self.hn_db))
        self.logger.con_out("Domains Obfuscated - %s" , len(self.dn_db))
        self.logger.con_out("Total Files Analyzed - %s", self.file_count)
        self.logger.con_out("*** SOSCleaner Artifacts ***")
        self._create_reports()
        self._create_archive()

        return_data = [self.archive_path, self.logfile, self.ip_report]
        if self.process_hostnames:
            return_data.append(self.hn_report)
        if len(self.dn_db) >= 1:
            return_data.append(self.dn_report)

        return return_data
