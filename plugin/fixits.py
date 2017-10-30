# -*- coding: utf-8 -*-

"""Fixits handling.

Indexing result evaluation, the frontend for the monitor process.
"""

import sublime
import sublime_plugin

import logging

from os import path

from . import jobs
from . import settings
from . import indicator

log = logging.getLogger("RTags")

class Category:
    WARNING = "warning"
    ERROR = "error"

class Controller():
    THEMES_PATH = "themes/Default"
    PACKAGE_PATH = "Packages/RTagsComplete"

    CATEGORIES = [ Category.WARNING, Category.ERROR ]

    CATEGORY_FLAGS = {
        Category.WARNING: sublime.DRAW_NO_FILL,
        Category.ERROR: sublime.DRAW_NO_FILL
    }

    PHANTOMS_TAG = "rtags_phantoms"

    def __init__(self, supported):
        self.supported = supported
        self.regions = {}
        self.issues = None
        self.waiting = False
        self.expecting = False
        self.filename = None
        self.view = None
        self.results_key = settings.SettingsManager.get('results_key', 'rtags_result_indicator')
        self.templates = {}
        self.navigation_items = None
        self.indicator = indicator.ProgressIndicator()

        names = ["phantom"]

        for category in self.CATEGORIES:
            self.templates[category] = {}
            for name in names:
                filename = "{}_{}.html".format(category, name)
                filepath = path.join(
                    path.dirname(path.dirname(__file__)),
                    self.THEMES_PATH,
                    filename)

                with open(filepath, 'rb') as file:
                    self.templates[category][name] = file.read().decode('utf-8')

    def as_html(self, template, message):
        padded = template.replace('{', '{{').replace('}', '}}')
        substituted = padded.replace('[', '{').replace(']', '}')
        return substituted.format(message)

    def on_select(self, res):
        (file, line, col) = self.navigation_items[res]
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)

    def on_highlight(self, res):
        (file, line, col) = self.navigation_items[res]
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def show_selector(self, view):
        if not supported_view(view):
            return

        if view.file_name() != self.filename:
            return

        def issue_to_panel_item(issue):
            return [
                issue['message'],
                "{}:{}:{}".format(self.filename.split('/')[-1], issue['line'], issue['column'])]

        items = list(map(issue_to_panel_item, self.issues['error']))
        items += list(map(issue_to_panel_item, self.issues['warning']))

        def issue_to_navigation_item(issue):
            return [self.filename, issue['line'], issue['column']]

        self.navigation_items = list(map(issue_to_navigation_item, self.issues['error']))
        self.navigation_items += list(map(issue_to_navigation_item, self.issues['warning']))

        # If there is only one result no need to show it to user
        # just do navigation directly.
        if len(items) == 1:
            self.on_select(0)
            return

        view.window().show_quick_panel(
            items,
            self.on_select,
            sublime.MONOSPACE_FONT,
            -1,
            self.on_highlight)

    def category_key(self, category):
        return "rtags-{}-mark".format(category)

    def clear_regions(self):
        if not self.view:
            return
        log.debug("Clearing regions from view")
        for key in self.regions.keys():
            self.view.erase_regions(self.category_key(key));

    def show_regions(self):
        scope_names = {'error': 'region.redish', 'warning': 'region.yellowish'}
        for category, regions in self.regions.items():
            self.view.add_regions(
                self.category_key(category),
                [region['region'] for region in regions],
                scope_names[category],
                "",
                Controller.CATEGORY_FLAGS[category])

    def clear_phantoms(self):
        if not self.view:
            return
        log.debug("Clearing phantoms from view")
        self.view.erase_phantoms(Controller.PHANTOMS_TAG)

    def update_phantoms(self, issues):
        if not self.view:
            return

        self.phantom_set = sublime.PhantomSet(self.view, Controller.PHANTOMS_TAG)

        def issue_to_phantom(category, issue):
            point = self.view.text_point(issue['line']-1, 0)
            start = self.view.line(point).a
            return sublime.Phantom(
                sublime.Region(start, start+1),
                self.as_html(self.templates[category]['phantom'], issue['message']),
                sublime.LAYOUT_BLOCK)

        phantoms = list(map(lambda p: issue_to_phantom('error', p), issues['error']))
        phantoms += list(map(lambda p: issue_to_phantom('warning', p), issues['warning']))

        self.phantom_set.update(phantoms)

    def update_regions(self, issues):

        def issue_to_region(issue):
            start = self.view.text_point(issue['line']-1, issue['column']-1)

            if issue['length'] > 0:
                end = self.view.text_point(issue['line']-1, issue['column']-1 + issue['length'])
            else:
                end = self.view.line(start).b

            return {
                "region": sublime.Region(start, end),
                "message": issue['message']}

        self.regions = {
            'warning': list(map(issue_to_region, issues['warning'])),
            'error': list(map(issue_to_region, issues['error']))
        }

    def clear_results(self):
        if not self.view:
            return

        log.debug("Clearing results from view {}".format(self.view))
        self.view.erase_status(self.results_key)

    def update_results(self, issues):
        results = []

        error_count = len(issues['error'])
        warning_count = len(issues['warning'])

        if error_count > 0:
            results.append("⛔: {}".format(error_count))
        if warning_count > 0:
            results.append("✋: {}".format(warning_count))
        if len(results) == 0:
            results.append("✅")

        self.view.set_status(self.results_key, "RTags {}".format(" ".join(results)))

    def clear(self, view=None):
        if not self.view:
            return

        # Skip of we wanted to clear a specific view but never drew onto it.
        #if view and (view != self.view):
        #    return

        self.clear_results()
        self.clear_regions()
        self.clear_phantoms()
        self.regions = {}
        self.issues = None

    def unload(self):
        self.indicator.stop()
        self.clear()

    def update(self, filename, issues):
        log.debug("Got indexing results for {}".format(filename))

        if not self.supported:
            log.debug("Fixits are disabled")
            return

        if not self.view:
            log.warning("There is no view")
            return

        if filename != self.filename:
            log.warning("Got update for {} which is not {}".format(filename, self.filename))
            return

        self.update_results(issues)
        self.update_regions(issues)
        self.update_phantoms(issues)
        self.show_regions()
        self.issues = issues

    def indexing_done_callback(self, future):
        #def indexing_callback(self, filename, view):
        log.debug("Indexing done callback hit {}".format(future))

        self.indicator.stop()

        if not future.done():
            log.warning("Indexing failed")
            return

        if future.cancelled():
            log.warning("Indexing was cancelled")
            return

        (returncode, job_id, out) = future.result()

        if returncode != 0:
            log.debug("Indexing failed with returncode {}".format(returncode))
            return

        log.debug("Triggering diagnosis for the indexed file")

        # For some bizarre reason a reindexed file that does not have any
        # fixits or warnings will not return anything in `rc -m`, hence
        # we need to force such result again via `rc --diagnose`.
        jobs.JobController.run_sync(jobs.RTagsJob(
            "RTDiagnoseJob" + jobs.JobController.next_id(),
            ['--diagnose', self.filename]))

    def reindex(self, view, saved):
        log.debug("Reindex hit {} {} {}".format(self, view, saved))

        self.clear()

        if not self.supported:
            log.debug("Fixits are disabled")
            return

        self.filename = view.file_name()
        self.view = view
        self.indicator.start(view)

        jobs.JobController.run_async(jobs.MonitorJob("RTMonitorJob"))

        text = b''

        if not saved:
            text = bytes(view.substr(sublime.Region(0, view.size())), "utf-8")

        jobs.JobController.run_async(
            jobs.ReindexJob(
                "RTReindexJob",
                self.filename,
                text),
            self.indexing_done_callback)

        log.debug("Expecting indexing results for {}".format(self.filename))