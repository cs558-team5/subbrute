#!/usr/bin/python
#
#SubBrute v1.0
#A (very) fast subdomain enumeration tool.
#Written by Rook
#
import re
import time
import optparse
import os
import signal
import sys
import random
import dns.resolver
from threading import Thread
import commands
import socket
import time
#support for python 2.7 and 3
try:
    import queue
except:
    import Queue as queue

#exit handler for signals.  So ctrl+c will work,  even with py threads. 
def killme(signum = 0, frame = 0):
    os.kill(os.getpid(), 9)

def create(n, constructor=list):
    for _ in xrange(n):
        yield constructor()

class lookup(Thread):
    def __init__(self, domains_for_thread, out_q, foundDC_q, subdomains, wildcard = False, resolver_list = []):
        Thread.__init__(self)
        self.out_q = out_q
        self.domains_for_thread = domains_for_thread
        self.wildcard = wildcard
        self.resolver_list = resolver_list
        self.resolver = dns.resolver.Resolver()
        self.subdomains = subdomains
        self.resolver.lifetime = 1.0
        self.resolver.Timeoutout = 0.5
        self.foundDC_q = foundDC_q

        if len(self.resolver.nameservers):
            self.backup_resolver = self.resolver.nameservers
        else:
            #we must have a resolver,  and this is the default resolver on my system...
            self.backup_resolver = ['127.0.0.1']
        if len(self.resolver_list):
            self.resolver.nameservers = self.resolver_list




    def check(self, host):
        slept = 0
        while True:
            try:
                answer = self.resolver.query(host)
                if answer:
                    return str(answer[0])
                else:
                    return False
            except Exception as e:

                if type(e) == dns.resolver.Timeout:
                    #print "Timeout"
                    return False
                elif type(e) == dns.resolver.NoAnswer:
                    #print "NoAnswer"
                    return False
                elif type(e) == dns.resolver.NXDOMAIN:
                    #not found
                    return False
                else:
                    return False

                # if type(e) == dns.resolver.NXDOMAIN:
                #     #not found
                #     return False
                # elif type(e) == dns.resolver.NoAnswer  or type(e) == dns.resolver.Timeout:
                #     if slept == 4:
                #         #This dns server stopped responding.
                #         #We could be hitting a rate limit.
                #         if self.resolver.nameservers == self.backup_resolver:
                #             #if we are already using the backup_resolver use the resolver_list
                #             self.resolver.nameservers = self.resolver_list
                #         else:
                #             #fall back on the system's dns name server
                #             self.resolver.nameservers = self.backup_resolver
                #     elif slept > 5:
                #         #hmm the backup resolver didn't work, 
                #         #so lets go back to the resolver_list provided.
                #         #If the self.backup_resolver list did work, lets stick with it.
                #         self.resolver.nameservers = self.resolver_list
                #         #I don't think we are ever guaranteed a response for a given name.
                #         return False
                #     #Hmm,  we might have hit a rate limit on a resolver.
                #     time.sleep(1)
                #     slept += 1
                #     #retry...
                # elif type(e) == IndexError:
                #     #Some old versions of dnspython throw this error,
                #     #doesn't seem to affect the results,  and it was fixed in later versions.
                #     pass
                # else:
                #     #dnspython threw some strange exception...
                #     raise e

    def check_DC(self, test):
        # Check found domain for DC
        command = 'nslookup -q=srv _ldap._tcp.dc._msdcs.'+test
        result = commands.getstatusoutput(command)

        if result[1].find("** server can't find")==-1:

            # Found DC, extract names
            sec = 'service = 0 100 389 '
            lines = result[1].split('\n')
            for line in lines:
                loc = line.find(sec)
                if loc>0:
                    dc_name = line[loc+len(sec):-1]
                    self.foundDC_q.put(dc_name)
                    
                    # Check if ports open
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(10)
                    ports_to_scan = [389, 100]
                    open_ports = []
                    for port in ports_to_scan:
                        result = sock.connect_ex((dc_name,port))
                        if result == 0:
                            open_ports.append(str(port))

                    # Print out finding
                    if len(open_ports)>0:
                        print dc_name+" | Open ports: "+' '.join(open_ports)
                    else:
                        print dc_name+" | No open ports"


    def run(self):

        domains_to_check = self.domains_for_thread
        subdomains = self.subdomains

        for subdomain in subdomains:

            if subdomain=='':
                continue

            for domain in domains_to_check:
                if domain == '':
                    continue

                test = "%s.%s" % (subdomain, domain)
                #print "Checking: "+test
                addr = self.check(test)
                if addr and addr != self.wildcard:
                    self.out_q.put(test)
                    #Check if DC
                    self.check_DC(test)



        # Done
        self.out_q.put(False)


#Return a list of unique sub domains,  sorted by frequency.
def extract_subdomains(file_name):
    subs = {}
    sub_file = open(file_name).read()
    #Only match domains that have 3 or more sections subdomain.domain.tld
    domain_match = re.compile("([a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*)+")
    f_all = re.findall(domain_match, sub_file)
    del sub_file
    for i in f_all:
        if i.find(".") >= 0:
            p = i.split(".")[0:-1]
            #gobble everything that might be a TLD
            while p and len(p[-1]) <= 3:
                p = p[0:-1]
            #remove the domain name
            p = p[0:-1]
            #do we have a subdomain.domain left?
            if len(p) >= 1:
                #print(str(p) + " : " + i)
                for q in p:
                    if q :
                        #domain names can only be lower case.
                        q = q.lower()
                        if q in subs:
                            subs[q] += 1
                        else:
                            subs[q] = 1
    #Free some memory before the sort...
    del f_all
    #Sort by freq in desc order
    subs_sorted = sorted(subs.keys(), key = lambda x: subs[x], reverse = True)
    return subs_sorted

def check_resolvers(file_name):
    ret = []
    resolver = dns.resolver.Resolver()

    # Change default timeout
    resolver.lifetime = 1.0

    res_file = open(file_name).read()
    for server in res_file.split("\n"):
        server = server.strip()
        if server:
            resolver.nameservers = [server]
            try:
                resolver.query("www.google.com")
                #should throw an exception before this line.
                ret.append(server)
            except:
                pass
    return ret

def run_target(domains, subdomains, resolve_list, thread_count):
    #The target might have a wildcard dns record...
    wildcard = False
    try:

        resp = dns.resolver.Resolver().query("would-never-be-a-domain-name-" + str(random.randint(1, 9999)) + "." + domains[0])
        wildcard = str(resp[0])
    except:
        pass

    # All get same output queue
    out_q = queue.Queue()

    # Create queue for DC checking
    foundDC_q = queue.Queue()

    # Split up domains across threads
    domains_for_thread = list(create(thread_count))
    if len(domains)<thread_count:# Error check
        print "Domains < Threads"
        sys.exit(1)
    else:
        for i in range(len(domains)):
            target_thread = i % thread_count
            domains_for_thread[ target_thread ].append( domains[i] )




    #Terminate the queue
    step_size = int(len(resolve_list) / thread_count)
    #Split up the resolver list between the threads. 
    if step_size <= 0:
        step_size = 1
    step = 0
    for i in range(thread_count):
        threads.append( lookup( domains_for_thread[i], out_q, foundDC_q, subdomains, wildcard , resolve_list[step:step + step_size]  ))
        threads[-1].start()
    step += step_size
    if step >= len(resolve_list):
        step = 0

    threads_remaining = thread_count
    while True:
        try:
            d = out_q.get(True, 10)
            #we will get an empty exception before this runs. 
            if not d:
                threads_remaining -= 1
            else:
                #print(d)
                pass
        except queue.Empty:
            pass
            
        #make sure everyone is complete
        if threads_remaining <= 0:
            break

if __name__ == "__main__":
    parser = optparse.OptionParser("usage: %prog [options] target")
    parser.add_option("-c", "--thread_count", dest = "thread_count",
              default = 10, type = "int",
              help = "(optional) Number of lookup theads to run,  more isn't always better. default=10")
    parser.add_option("-s", "--subs", dest = "subs", default = "subs.txt",
              type = "string", help = "(optional) list of subdomains,  default='subs.txt'")
    parser.add_option("-r", "--resolvers", dest = "resolvers", default = "resolvers.txt",
              type = "string", help = "(optional) A list of DNS resolvers, if this list is empty it will OS's internal resolver default='resolvers.txt'")
    parser.add_option("-f", "--filter_subs", dest = "filter", default = "",
              type = "string", help = "(optional) A file containing unorganized domain names which will be filtered into a list of subdomains sorted by frequency.  This was used to build subs.txt.")
    parser.add_option("-t", "--target_file", dest = "targets", default = "",
              type = "string", help = "(optional) A file containing a newline delimited list of domains to brute force.")

    (options, args) = parser.parse_args()

    if len(args) < 1 and options.filter == "" and options.targets == "":
        parser.error("You must provie a target! Use -h for help.")

    if options.filter != "":
        #cleanup this file and print it out
        for d in extract_subdomains(options.filter):
            print(d)
        sys.exit()

    if options.targets != "":
        targets = open(options.targets).read().split("\n")
    else:
        targets = args #multiple arguments on the cli:  ./subbrute.py google.com gmail.com yahoo.com

    subdomains = open(options.subs).read().split("\n")

    resolve_list = check_resolvers(options.resolvers)
    threads = []
    signal.signal(signal.SIGINT, killme)

    # Run across all domains, targets are domains we are looking across
    run_target(targets, subdomains, resolve_list, options.thread_count)









