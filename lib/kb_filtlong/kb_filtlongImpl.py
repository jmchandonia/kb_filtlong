# -*- coding: utf-8 -*-
#BEGIN_HEADER
import logging
import os
import re
import uuid
import json
import subprocess
import sys

from installed_clients.WorkspaceClient import Workspace
from installed_clients.ReadsUtilsClient import ReadsUtils
from installed_clients.KBaseReportClient import KBaseReport
#END_HEADER


class kb_filtlong:
    '''
    Module Name:
    kb_filtlong

    Module Description:
    A KBase module: kb_filtlong
    '''

    ######## WARNING FOR GEVENT USERS ####### noqa
    # Since asynchronous IO can lead to methods - even the same method -
    # interrupting each other, you must be *very* careful when using global
    # state. A method could easily clobber the state set by another while
    # the latter method is running.
    ######################################### noqa
    VERSION = "0.0.1"
    GIT_URL = "git@github.com:jmchandonia/kb_filtlong.git"
    GIT_COMMIT_HASH = "004197d6e219df11667001f50a4ff668fab8b6f7"

    #BEGIN_CLASS_HEADER
    def log(self, target, message):
        if target is not None:
            target.append(message)
        print(message)
        sys.stdout.flush()

    # get long reads
    def download_long(self, console, warnings, token, wsname, lib):
        try:
            # object info
            try:
                wsClient = Workspace(self.workspaceURL, token=token)
            except Exception as e:
                raise ValueError("unable to instantiate wsClient. "+str(e))

            [OBJID_I, NAME_I, TYPE_I, SAVE_DATE_I, VERSION_I, SAVED_BY_I, WSID_I,
                WORKSPACE_I, CHSUM_I, SIZE_I, META_I] = range(11)  # object_info tuple

            obj_id = {'ref': lib if '/' in lib else (wsname + '/' + lib)}
            lib_obj_info = wsClient.get_object_info_new({'objects': [obj_id]})[0]
            lib_obj_type = lib_obj_info[TYPE_I]
            lib_obj_type = re.sub('-[0-9]+\.[0-9]+$', "", lib_obj_type)  # remove trailing version
            lib_ref = str(lib_obj_info[WSID_I])+'/' + \
                str(lib_obj_info[OBJID_I])+'/'+str(lib_obj_info[VERSION_I])

            ruClient = ReadsUtils(url=self.callbackURL, token=token)
            self.log(console, "Getting long reads (from reads library object).\n")
            result = ruClient.download_reads({'read_libraries': [lib_ref],
                                              'interleaved': 'false'})
            long_reads_path = result['files'][lib_ref]['files']['fwd']

        except Exception as e:
            raise ValueError('Unable to download long reads\n' + str(e))
        return long_reads_path

    #END_CLASS_HEADER

    # config contains contents of config file in a hash or None if it couldn't
    # be found
    def __init__(self, config):
        #BEGIN_CONSTRUCTOR
        self.cfg = config
        self.cfg['SDK_CALLBACK_URL'] = os.environ['SDK_CALLBACK_URL']
        self.cfg['KB_AUTH_TOKEN'] = os.environ['KB_AUTH_TOKEN']
        self.callbackURL = self.cfg['SDK_CALLBACK_URL']
        self.workspaceURL = config['workspace-url']
        self.shockURL = config['shock-url']
        self.scratch = os.path.abspath(config['scratch'])
        if not os.path.exists(self.scratch):
            os.makedirs(self.scratch)
        #END_CONSTRUCTOR
        pass


    def run_kb_filtlong(self, ctx, params):
        """
        This example function accepts any number of parameters and returns results in a KBaseReport
        :param params: instance of mapping from String to unspecified object
        :returns: instance of type "ReportResults" -> structure: parameter
           "report_name" of String, parameter "report_ref" of String
        """
        # ctx is the context object
        # return variables are: output
        #BEGIN run_kb_filtlong
        console = []
        warnings = []
        self.log(console, 'Running run_kb_filtlong with params:\n{}'.format(
            json.dumps(params, indent=1)))
        token = self.cfg['KB_AUTH_TOKEN']


        # param checks
        required_params = ['workspace_name',
                           'input_reads_library',
                           'output_reads_name',
                           'min_read_length']
        for required_param in required_params:
            if required_param not in params or params[required_param] is None:
                raise ValueError("Must define required param: '"+required_param+"'")

        # load provenance
        provenance = [{}]
        if 'provenance' in ctx:
            provenance = ctx['provenance']
        if 'input_ws_objects' not in provenance[0]:
            provenance[0]['input_ws_objects'] = []
        if 'input_reads_library' in params and params['input_reads_library'] is not None:
            provenance[0]['input_ws_objects'].append(params['input_reads_library'])

        # build command line
        cmd = 'filtlong'

        if 'min_read_length' in params and params['min_read_length'] is not None:
            cmd += ' --min_length '+str(params['min_read_length'])

        if 'keep_percent' in params and params['keep_percent'] is not None:
            cmd += ' --keep_percent '+str(params['keep_percent'])

        if 'target_bases' in params and params['target_bases'] is not None:
            cmd += ' --target_bases '+str(params['target_bases'])
            

        # download long library
        longLib = self.download_long(
            console, warnings, token, params['workspace_name'], params['input_reads_library'])
        cmd += ' '+longLib

        # output file
        outputFile = os.path.join(self.scratch, "filtlong_output_"+str(uuid.uuid4())+".fastq.gz")
        cmd += ' | gzip > '+outputFile

        # run it
        self.log(console, "command: "+cmd)
        cmdProcess = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, shell=True)
        for line in cmdProcess.stdout:
            self.log(console, line.decode("utf-8").rstrip())
        cmdProcess.wait()
        if cmdProcess.returncode != 0:
            raise ValueError('Error running '+cmd)

        # save reads
        ruClient = ReadsUtils(url=self.callbackURL, token=token)
        self.log(console, 'Uploading filtered reads: '+params['output_reads_name'])
        result = ruClient.upload_reads({'wsname': params['workspace_name'],
                                        'name': params['output_reads_name'],
                                        'source_reads_ref': params['input_reads_library'],
                                        'fwd_file': outputFile})

        # build report
        self.log(console, 'Generating and saving report')
        reads_ref = params['workspace_name'] + '/' + params['output_reads_name']

        report_text = ''
        report_text += 'Filtlong results saved to: ' + reads_ref + '\n'
        
        reportClient = KBaseReport(self.callback_url)
        report_output = reportClient.create_extended_report(
            {'message': report_text,
             'objects_created': [{'ref': reads_ref, 'description': 'Filtered reads'}],
             'report_object_name': 'kb_filtlong_report_' + str(uuid.uuid4()),
             'workspace_name': params['workspace_name']})
             
        output = {
            'report_name': report_output['name'],
            'report_ref': report_output['ref'],
        }
        #END run_kb_filtlong

        # At some point might do deeper type checking...
        if not isinstance(output, dict):
            raise ValueError('Method run_kb_filtlong return value ' +
                             'output is not type dict as required.')
        # return the results
        return [output]
    def status(self, ctx):
        #BEGIN_STATUS
        returnVal = {'state': "OK",
                     'message': "",
                     'version': self.VERSION,
                     'git_url': self.GIT_URL,
                     'git_commit_hash': self.GIT_COMMIT_HASH}
        #END_STATUS
        return [returnVal]
