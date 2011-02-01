# -*- coding: utf-8 -*-

# Copyright © 2010-2011 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.

import logging
import traceback
import os
import sys
from optparse import OptionParser, SUPPRESS_HELP

from pulp.server import auditing
from pulp.server.config import config
from pulp.server.db import connection

# the db connection and auditing need to be initialied before any further
# imports since the imports execute initialization code relying on the
# db/auditing to be setup
connection.initialize()
auditing.initialize()

_log = logging.getLogger('pulp')

from pulp.server.db.migrate.validate import validate
from pulp.server.db.version import (
    VERSION, get_version_in_use, set_version, is_validated, set_validated)
from pulp.server.db.version import clean_db as clean_versions

def parse_args():
    parser = OptionParser()
    parser.add_option('--auto', action='store_true', dest='auto',
                      default=False, help=SUPPRESS_HELP)
    parser.add_option('--force', action='store_true', dest='force',
                      default=False, help='force migration to run, ignoring "version" in db')
    parser.add_option('--log-file', dest='log_file',
                      default='/var/log/pulp/db.log',
                      help='file for log messages')
    parser.add_option('--log-level', dest='log_level', default='info',
                      help='level of logging (debug, info, error, critical)')
    options, args = parser.parse_args()
    if args:
        parser.error('unknown arguments: %s' % ', '.join(args))
    return options


def start_logging(options):
    level = getattr(logging, options.log_level.upper(), logging.INFO)
    logger = logging.getLogger('pulp') # imitate the pulp log handler
    logger.setLevel(level)
    handler = logging.FileHandler(options.log_file)
    logger.addHandler(handler)


def get_migration_modules():
    # ADD YOUR MIGRATION MODULES HERE
    # modules that perform the datamodel migration for each version
    from pulp.server.db.migrate import one, two
    # NOTE these are ordered from the smallest to largest (oldest to newest)
    return (one, two)


def datamodel_migration(options):
    version = get_version_in_use()
    assert version <= VERSION, \
            'version in use (%d) greater than expected version (%d)' % \
            (version, VERSION)
    if version == VERSION:
        print 'data model in use matches the current version'
        return os.EX_OK
    for mod in get_migration_modules():
        # it is assumed here that each migration module will have two members:
        # 1. version - an integer value of the version the module migrates to
        # 2. migrate() - a function that performs the migration
        if mod.version <= version:
            continue
        if mod.version > VERSION:
            print >> sys.stderr, \
                    'migration provided for higer version than is expected'
            return os.EX_OK
        try:
            mod.migrate()
        except Exception, e:
            _log.critical(str(e))
            _log.critical(''.join(traceback.format_exception(*sys.exc_info())))
            _log.critical('migration to data model version %d failed' %
                          mod.version)
            print >> sys.stderr, \
                    'migration to version %d failed, see %s for details' % \
                    (mod.version, options.log_file)
            return os.EX_SOFTWARE
        set_version(mod.version)
        version = mod.version
    if version < VERSION:
        return os.EX_DATAERR
    return os.EX_OK


def datamodel_validation(options):
    errors = 0
    if not is_validated():
        errors = validate()
    if errors:
        print >> sys.stderr, '%d errors on validation, see %s for details' % \
                (errors, options.log_file)
        return os.EX_DATAERR
    set_validated()
    return os.EX_OK


def main():
    options = parse_args()
    start_logging(options)
    if options.auto and not config.getboolean('database', 'auto_upgrade'):
        print >> sys.stderr, 'pulp is not configured for auto upgrade'
        return os.EX_CONFIG
    if options.force:
        print 'Cleaning previous versions'
        clean_versions()
    ret = datamodel_migration(options)
    if ret != os.EX_OK:
        return ret
    ret = datamodel_validation(options)
    if ret != os.EX_OK:
        return ret
    print 'database migration to version %d complete' % VERSION
    return os.EX_OK
