# -*- coding: utf-8 -*-

"""RTagsComplete plugin for Sublime Text 3.

Jobs are scheduled process runs.

"""

import re
import sublime
import sublime_plugin
import subprocess

import logging

import xml.etree.ElementTree as etree

from concurrent import futures
from functools import partial
from time import time
from threading import RLock

from . import settings

log = logging.getLogger("RTags")

class RTagsJob():

    def __init__(self, job_id, command_info, data=b'', communicate=None, nodebug=False):
        self.job_id = job_id
        self.command_info = command_info
        self.data = data
        self.p = None
        self.error = None
        if communicate:
            self.callback = communicate
        else:
            self.callback = self.communicate
        self.nodebug = nodebug

    def prepare_command(self):
        return [settings.SettingsManager.get('rc_path')] + self.command_info

    def stop(self):
        log.debug("Killing job {}".format(self.p))
        if self.p:
            self.p.kill()
        self.p = None
        return

    def communicate(self, process, timeout=None):
        if not self.nodebug:
            log.debug("Static communicate with timeout {} for {}".format(timeout, self.callback))
        if not timeout:
            timeout = settings.SettingsManager.get('rc_timeout')
        (out, _) = process.communicate(input=self.data, timeout=timeout)
        if not self.nodebug:
            log.debug("Static communicate terminating")
        return out

    def run_process(self, timeout=None):
        out = b''
        command = self.prepare_command()
        returncode = None

        if not self.nodebug:
            log.debug("Starting process job {}".format(command))

        start_time = time()

        try:
            with subprocess.Popen(
                command,
                stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE) as process:

                self.p = process

                if not self.nodebug:
                    log.debug("Process running with timeout {}, input-length {}".format(timeout, len(self.data)))
                    log.debug("Communicating with process via {}".format(self.callback))

                out = self.callback(process)

                returncode = process.returncode

        except Exception as e:
            log.error("Aborting with exception: {}".format(e))

        if not self.nodebug:
            log.debug("Return code {}, output-length: {}".format(returncode, len(out)))
            log.debug("Process job ran for {:2.2f} seconds".format(time() - start_time))

        return (returncode, self.job_id, out)


class CompletionJob(RTagsJob):

    def __init__(self, view, completion_job_id, filename, text, size, row, col):
        command_info = []

        # Auto-complete switch.
        command_info.append('-l')
        # The query.
        command_info.append('{}:{}:{}'.format(filename, row + 1, col + 1))
        # We want to complete on an unsaved file.
        command_info.append('--unsaved-file')
        # We launch rc utility with both filename:line:col and filename:length
        # because we're using modified file which is passed via stdin (see --unsaved-file
        # switch)
        command_info.append('{}:{}'.format(filename, size))
        # Make this query block until getting answered.
        command_info.append('--synchronous-completions')

        RTagsJob.__init__(self, completion_job_id, command_info, text)

        self.view = view

    def run(self):
        (_, _, out)  = self.run_process(60)
        suggestions = []
        for line in out.splitlines():
            # log.debug(line)
            # line is like this
            # "process void process(CompletionThread::Request *request) CXXMethod"
            # "reparseTime int reparseTime VarDecl"
            # "dump String dump() CXXMethod"
            # "request CompletionThread::Request * request ParmDecl"
            # we want it to show as process()\tCXXMethod
            #
            # output is list of tuples: first tuple element is what we see in popup menu
            # second is what inserted into file. '$0' is where to place cursor.
            # TODO play with $1, ${2:int}, ${3:string} and so on.
            elements = line.decode('utf-8').split()
            suggestions.append(('{}\t{}'.format(' '.join(elements[1:-1]), elements[-1]),
                                '{}$0'.format(elements[0])))

        log.debug("Completion done")
        return (self.view, self.job_id, suggestions)


class ReindexJob(RTagsJob):

    def __init__(self, job_id, filename, text=b''):
        command_info = ["-V", filename ]
        if len(text):
            command_info += [ "--unsaved-file", "{}:{}".format(filename,len(text)) ]

        RTagsJob.__init__(self, job_id, command_info, text)

    def run(self):
        (returncode, _, out)  = self.run_process(300)
        return (returncode, self.job_id, out)


class MonitorJob(RTagsJob):

    def __init__(self, job_id):
        RTagsJob.__init__(self, job_id, ['-m'], b'', self.communicate)
        self.error = None

    def run(self):
        (returncode, _, out) = self.run_process()
        return (returncode, self.job_id, out)

    def communicate(self, process, timeout=None):
        log.debug("In data callback {}".format(process.stdout))
        rgxp = re.compile(r'<(\w+)')
        buffer = ''  # xml to be parsed
        start_tag = ''

        for line in iter(process.stdout.readline, b''):
            line = line.decode('utf-8')
            process.poll()

            if not start_tag:
                start_tag = re.findall(rgxp, line)
                start_tag = start_tag[0] if len(start_tag) else ''

            buffer += line

            if "Can't seem to connect to server" in line:
                log.error(line)
                self.error = "Can't seem to connect to server. Make sure RTags `rdm` is running, then retry."
                return b''

            # Keep on accumulating XML data until we have a closing tag,
            # matching our start_tag.

            if '</{}>'.format(start_tag) in line:
                tree = etree.fromstring(buffer)
                # OK, we received some chunk
                # check if it is progress update
                if (tree.tag == 'progress' and
                        tree.attrib['index'] == tree.attrib['total'] and
                        navigation_helper.flag == NavigationHelper.NAVIGATION_REQUESTED):
                    # notify about event
                    sublime.active_window().active_view().run_command(
                        'rtags_location',
                        {'switches': navigation_helper.switches})

                if  tree.tag == 'checkstyle':
                    key = 0

                    mapping = {
                        'warning': 'warning',
                        'error': 'error',
                        'fixit': 'error'
                    }

                    issues = {
                        'warning': [],
                        'error': []
                    }

                    for file in tree.findall('file'):
                        for error in file.findall('error'):
                            if error.attrib["severity"] in mapping.keys():
                                issue = {}
                                issue['line'] = int(error.attrib["line"])
                                issue['column'] = int(error.attrib["column"])
                                if 'length' in error.attrib:
                                    issue['length'] = int(error.attrib["length"])
                                else:
                                    issue['length'] = -1
                                issue['message'] = error.attrib["message"]

                                issues[mapping[error.attrib["severity"]]].append(issue)

                        log.debug("Got fixits to send")

                        sublime.active_window().active_view().run_command(
                            'rtags_fixit',
                            {
                                'filename': file.attrib["name"],
                                'issues': issues
                            })

                buffer = ''
                start_tag = ''

        log.debug("Data callback terminating")
        return b''


class JobController():
    pool = futures.ThreadPoolExecutor(max_workers=4)
    lock = RLock()
    thread_map = {}
    unique_index = 0

    def next_id():
        JobController.unique_index += 1
        return "{}".format(JobController.unique_index)

    def run_async(job, callback=None):
        with JobController.lock:
            if job.job_id in JobController.thread_map.keys():
                log.debug("Job {} still active".format(job.job_id))
                return

            log.debug("Starting async job {}".format(job.job_id))

            future = JobController.pool.submit(job.run)
            if callback:
                future.add_done_callback(callback)
            future.add_done_callback(
                partial(JobController.done, job_id=job.job_id))

            JobController.thread_map[job.job_id] = (future, job)

    def run_sync(job, timeout=None):
        # Debug logging every single run_sync request is too verbose
        # if polling is used for gathering rc's indexing status
        #log.debug("Starting blocking job {} with timeout {}".format(job.job_id, timeout))
        return job.run_process(timeout)

    def stop(job_id):
        future = None
        job = None

        with JobController.lock:
            if job_id in JobController.thread_map.keys():
                (future, job) = JobController.thread_map[job_id]

        if not job:
            log.debug("Job not started")
            return

        log.debug("Stopping job {}={}".format(job_id, job.job_id))
        log.debug("Job {} should now disappear with {}".format(job_id, future))

        job.stop()

        log.debug("Waiting for job {}".format(job_id))
        future.cancel()
        future.result(15)

        if future.done():
            log.debug("Done with that job {}".format(job_id))
        if future.cancelled():
            log.debug("Stopped job {}".format(job_id))

    def done(future, job_id):
        log.debug("Job {} done".format(job_id))

        if not future.done():
            log.debug("Job wasn't really done")

        if future.cancelled():
            log.debug("Job was cancelled")

        with JobController.lock:
            del JobController.thread_map[job_id]
            log.debug("Removed bookkeeping for job {}".format(job_id))

    def job(job_id):
        job = None
        with JobController.lock:
            (_, job) = JobController.thread_map[job_id]
        return job

    def future(job_id):
        future = None
        with JobController.lock:
            (future, _) = JobController.thread_map[job_id]
        return future

    def stop_all():
        with JobController.lock:
            log.debug("Stopping running threads {}".format(list(JobController.thread_map)))
            for job_id in list(JobController.thread_map):
                JobController.stop(job_id)
