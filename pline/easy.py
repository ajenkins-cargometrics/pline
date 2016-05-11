import collections
import datetime
import os
import pprint
import sys

import envopt
import yaml

from . import base, pipeline, activities, resources, keywords, actions


class PipelineOptions(collections.MutableMapping):
    """
    Represents options for a pipeline.

    An instance of this class behaves like a dictionary, but values can either be stored in the object, or come from
    environment variables.
    """
    def __init__(self, options=None, defaults=None, env_prefix=None):
        """
        Initialize PipelineOptions instance.

        Option values come from a combination of the options dictionary, environment variables, and the defaults
        dictionary.  When looking up an option value, the options dictionary has highest precedence, then
        environment variables, and the defaults dictionary is checked last.

        :param options: A dictionary of option values
        :param defaults: A dictionary with default option values
        :param env_prefix: Environment variable name prefix.  If not empty, '_' will be appended to it.
        """
        if env_prefix:
            self._env_prefix = '{}_'.format(env_prefix)
        else:
            self._env_prefix = ''

        self._items = {}
        if options:
            self._items.update(options)
        if defaults:
            for k, v in defaults.iteritems():
                self._items.setdefault(k, self._getenv(k, v))

    def __iter__(self):
        # Not implemented because options can be looked up lazily by looking at environment variables, so to be
        # correct this would need to iterate over all environment variables with self._env_prefix
        raise NotImplementedError()

    def __setitem__(self, key, value):
        self._items[key] = value

    def __delitem__(self, key):
        # Not implemented because it would have to delete environment variables to be correct
        raise NotImplementedError()

    def __getitem__(self, key):
        if key in self._items:
            return self._items[key]
        val = self._getenv(key)
        if val is None:
            raise KeyError(key)
        return val

    def __len__(self):
        # Not implemented for the same reason __iter__ isn't implemented
        raise NotImplementedError()

    def _getenv(self, key, default=None):
        return os.environ.get('%s%s' % (self._env_prefix, key), default)


class EasyPipeline(pipeline.Pipeline):
    REQUIRED_OPTIONS = ('LOG_URI', 'PIPELINE_ROLE', 'PIPELINE_RESOURCE_ROLE', 'EC2_AMI', 'EC2_KEYPAIR', 'EC2_SUBNET',
                        'EC2_SECURITY_GROUP')

    def __init__(self, name, unique_id, options, desc=None, region='us-west-2'):
        """
        Intialize an EasyPipeline instance.

        :param name: The name of the pipeline
        :param unique_id: Unique id of the pipeline
        :param options: A PipelineOptions instance.  It will be available via the options property
        :param desc: A description of the pipeline
        :param region: The AWS region the pipeline will be deployed in
        """
        super(EasyPipeline, self).__init__(name=name, unique_id=unique_id, desc=desc, region=region)
        self.options = options
        if 'LOG_URI' not in self.options and 'LOG_URI_TEMPLATE' in self.options:
            self.options['LOG_URI'] = self.options['LOG_URI_TEMPLATE'].format(region=region, pipeline_name=name)

        missing_opts = [o for o in self.REQUIRED_OPTIONS if o not in self.options]
        if missing_opts:
            raise ValueError("The following required options are not set: {!r}".format(missing_opts))

        self.get_defaults()

    def _get_object(self, id):
        """
        Get a pipeline object by id
        :param id: The id of the object to get

        :return: The object with id, or None if not found
        """
        for o in self.objects.collection:
            if o.id == id:
                return o
        return None

    def _ensure_object(self, id, cls, **kwargs):
        """
        Get a pipeline object by id, creating it if it doesn't already exist

        :param id: The id of the object to get or create
        :param cls: The class of the object
        :param kwargs: Keyword args to pass the the class constructor when creating a new instance
        :return: The object
        """
        obj = self._get_object(id)
        if obj is None:
            obj = cls(id=id, **kwargs)
            self.add(obj)
        return obj

    def get_defaults(self):
        """
        Get the Default object for this pipeline, which contains default property values that all other objects
        inherit.
        """
        obj = self._ensure_object(
            'Default', base.DataPipelineObject,
            name='Default',
            scheduleType=keywords.scheduleType.ondemand,
            failureAndRerunMode=keywords.failureAndRerunMode.CASCADE,
            pipelineLogUri=self.options['LOG_URI'],
            role=self.options['PIPELINE_ROLE'],
            resourceRole=self.options['PIPELINE_RESOURCE_ROLE'])
        return obj

    def get_shell_command_activity(self, id):
        """
        Get the ShellCommandActivity object with id, creating it if necessary.

        Callers will need to set the command property to the command to run,  and the runsOn or workerGroup property to
        configure where it runs.
        :param id: Id of the object
        :return: a ShellCommandActivity
        """
        activity = self._ensure_object(
            id, activities.ShellCommandActivity,
            name=id,
            maximumRetries=0)
        return activity

    def get_schedule(self, id='DefaultSchedule'):
        """
        Gets the schedule object, creating it if necessary.

        When creating the schedule, the new schedule is also set as the default schedule for the pipeline, and
        scheduleType is set to CRON.  Callers should set the period and startDateTime properties.

        :param id:  Id of the object
        :return: a Schedule object
        """
        schedule = self._ensure_object(id, base.Schedule, name=id)
        defaults = self.get_defaults()
        defaults.scheduleType = keywords.scheduleType.cron
        defaults.schedule = schedule
        return schedule

    def get_ec2_resource(self, id):
        """
        Get an Ec2Resource object, creating it if necessary.

        Callers don't need to set any additional properties.

        :param id: Id of the object
        :return: an Ec2Resource object.
        """
        node = self._ensure_object(
            id, resources.Ec2Resource,
            name=id,
            actionOnTaskFailure=keywords.actionOnTaskFailure.terminate,
            actionOnResourceFailure=keywords.actionOnResourceFailure.retryAll,
            maximumRetries=1,
            terminateAfter='1 hours',
            imageId=self.options['EC2_AMI'],
            keyPair=self.options['EC2_KEYPAIR'],
            subnetId=self.options['EC2_SUBNET'],
            securityGroupIds=self.options['EC2_SECURITY_GROUP'])
        return node

    def get_sns_alarm(self, id):
        """
        Get an SnsAlarm object, creating it if necessary.

        Callers need to set the subject, message, and topicArn properties.

        :param id: Id of the object
        :return: An SnsAlarm object
        """
        alarm = self._ensure_object(
            id, actions.SnsAlarm,
            name=id,
            role=self.options['PIPELINE_ROLE'])
        return alarm

    def get_sns_failure_handler(self, id):
        """
        Get an SnsAlarm object specifically configured for use as an onError handler.

        The returned SnsAlarm has preset subject and message property values, which show the pipeline name, execution
        status, date of execution, and a link to dashboard for this pipeline.  Callers only need to set the topicArn.

        :param id: Id of the object.
        :return: An SnsAlarm object
        """
        date_fmt = "#{format(node.@scheduledStartTime,'YYYY-MM-dd')}"

        msg_body = """Pipeline: {name}
Status: #{{node.@status}}
Scheduled Time: #{{node.@scheduledStartTime}}

Pipeline dashboard:
https://console.aws.amazon.com/datapipeline/home?region={region}#ExecutionDetailsPlace:pipelineId=#{{@pipelineId}}&show=latest
        """.format(name=self.name, region=self.region_name)

        alarm = self._ensure_object(
            id, actions.SnsAlarm,
            name=id,
            role=self.options['PIPELINE_ROLE'],
            subject='{} FAILED on {}'.format(self.name, date_fmt),
            message=msg_body)
        return alarm


def main(setup_func, argv=None, env_prefix='PIPELINE'):
    """
    The main entry point for this module.

    Call this function to perform commandline-arg parsing, and then create the pipeline and call the user's pipeline
    setup function.   Here's how you could define a pipeline which just runs a hello world command::

        import pline.easy

        def setup(pipeline):
            activity = pipeline.get_shell_command_activity('HelloWorldActivity')
            activity.command = 'echo hello world'

        pline.easy.main(setup)

    :param setup_func: A function which will be called with the pipeline object.  It's responsible for setting up the
     pipeline.
    :param argv: The command-line arguments to parse.  Defaults to sys.argv[1:]
    :param env_prefix: Prefix for environment variable names used to pass in options.
    """

    cli_help = """
    AWS data pipeline builder.

    Usage:
      {progname} -n PIPELINE_NAME [-o OPTION...] [-c CFG_FILE...] [options]

    The following pipeline options must be defined in order for pipeline definitions to work.  Options can be defined
    using the -o option, via config file using the -c option, or via environment variables prefixed with {env_prefix}_.

    Required pipeline options:
      {required_options}

    Options:
      -n --name PIPELINE_NAME  Human readable name for pipeline
      -i --unique-id ID        Unique ID for pipeline
      -d --description DESCR   Description of pipeline
      -r --aws-region REGION   AWS Region [default: us-west-2]
      -a --activate            Activate the pipeline after creating it
      -o --option OPTION       An option value in KEY=VALUE format
      -c --config CFG_FILE     A config file in docker Envfile format.  Can be specified multiple times.
      --dry-run                Display a representation of pipeline definition without creating it.
    """.format(progname=os.path.basename(sys.argv[0]), env_prefix=env_prefix,
               required_options=', '.join(EasyPipeline.REQUIRED_OPTIONS))

    if argv is None:
        argv = sys.argv[1:]
    args = envopt.envopt(cli_help, argv=argv, env_prefix=env_prefix)

    name = args['--name']
    unique_id = args['--unique-id'] or "{}-{:%Y%m%d%H%M%S}".format(name, datetime.datetime.now())
    description = args['--description'] or ''
    region = args['--aws-region']

    options = {}
    for opt in args['--option']:
        parts = opt.split('=', 1)
        if len(parts) != 2:
            raise ValueError("Incorrectly formatted option '{}'.  Use KEY=VALUE format".format(opt))
        options[parts[0]] = parts[1]

    defaults = {}
    for cfgfile in args['--config']:
        cfg = yaml.load(file(cfgfile))
        defaults.update(cfg)

    pline_options = PipelineOptions(options, defaults, env_prefix)

    pline_obj = EasyPipeline(name=name, unique_id=unique_id, options=pline_options, desc=description, region=region)
    setup_func(pline_obj)

    if args['--dry-run']:
        pprint.pprint(pline_obj.payload())
    else:
        pline_obj.connect()
        response = pline_obj.create()
        print "pipelineId: {}".format(response['pipelineId'])
        if args['--activate']:
            pline_obj.activate()



