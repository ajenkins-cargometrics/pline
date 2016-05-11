# pline Python library

<img src="https://travis-ci.org/amancevice/pline.svg?branch=master"/>

AWS Data Pipeline Wrapper for `boto3`. Construct a Data Pipeline using Python objects.

Last updated: `0.4.2`

## Installation

```
pip install pline
```

## Overview

The payload `boto3` requires for a pipeline definition is somewhat complex. This library 
provides the tools to model your pipeline using Python objects and transform the payload
into the expected data structure.

```python
import pline

my_activity = pline.activities.ShellCommandActivity(
    name='MyActivity', id='Activity_adbc1234')
my_activity.command = "echo $1 $2"
my_activity.scriptArgument = ['hello', 'world']

dict(my_activity)
{ 'id'     : 'Activity_adbc1234',
  'name'   : 'MyActivity',
  'fields' : [ {'key': 'command',        'stringValue': 'echo $1 $2'},
               {'key': 'type',           'stringValue': 'ShellCommandActivity'},
               {'key': 'scriptArgument', 'stringValue': 'hello'},
               {'key': 'scriptArgument', 'stringValue': 'world'} ]}
 ```

## Easy Interface

The pline.easy module supports an easy way to create pipeline definitions, by providing a template that fills in many
of the details of the pipeline definition for you, so you only need to specify the parts that are unique to your 
pipeline.

Here is how you could define a trivial pipeline that just runs the command `echo Hello World`:

```python
import pline.easy

def setup(pipeline):
    activity = pipeline.get_shell_command_activity('HelloWorldActivity')
    activity.command = 'echo Hello World'

pline.easy.main(setup)
```

This defines a pipeline with an on-demand schedule, with a single ShellScriptActivity.  Assuming this code is saved in 
a file called create_pipeline.py, you could then create and activate this pipeline by running:

```bash
python create_pipeline.py --config defaults.yaml --name "Hello World" --activate
```

This would create the pipeline in AWS and activate it.  The defaults.yaml file is a file containing values for 
options that are required for pipeline definition, and "Hello World" will be the pipeline name.   See below for
the config file format.  Run

```bash
python create_pipeline.py -h
```

for command-line help, and for a list of the options which must be defined in defaults.yaml.
 
Now, let's make the example pipeline more realistic.  Let's add a schedule to make it run daily at 21:00 UTC, and
add an SNS error handler to the shell script activity.  We'll also allow configuring the message that's echoed.

```python
import datetime
import pline.easy

def setup(pipeline):
    error_handler = pipeline.get_sns_failure_handler('HelloWorldErrorHandler')
    error_handler.topicArn = pipeline.options['SNS_ARN']

    activity = pipeline.get_shell_command_activity('HelloWorldActivity')
    activity.command = 'echo Hello {}'.format(pipeline.options['RECIPIENT']
    activity.runsOn = pipeline.get_ec2_resource('HelloWorldNode')
    activity.onError = error_handler
    
    schedule = pipeline.get_schedule()
    schedule.period = '1 day'
    schedule.startDateTime = datetime.datetime.now().strftime('%Y-%m-%dT21:00:00')

pline.easy.main(setup)
```

This example showed several new things. It shows using the pipeline.options property to access configuration options, 
in this case the SNS_ARN and RECIPIENT options.  The onError handler showed creating an SnsAlarm, pre-configured with a 
generic message and subject which will show the pipeline name, exit status, execution date, and a link to the web 
console for the pipeline.  The `get_ec2_resource` method shows creating an EC2 resource.  It also shows creating a 
schedule for the pipeline.  The pipeline can be created with this command:

```bash
sns=arn:aws:sns:us-west-2:528461152743:adam-test
python create_pipeline.py -a -c defaults.yaml --name "Hello World" -o SNS_ARN=$sns -o RECIPIENT=Jim
```

In this case I passed in the config options using the -o flag.  I could also have passed them in by putting them
in a config file, or by setting the environment variables PIPELINE_SNS_ARN and PIPELINE_RECIPIENT.  The environment
variable prefix, `PIPELINE_`, can be changed by passing the `env_prefix=`, to `pline.easy.main`, as in:

```python
pline.easy.main(setup, env_prefix='HELLO')
```

Now you would use HELLO_SNS_ARN and HELLO_RECIPIENT as the environment variable names.

Here is the list of `get_xxx` methods currently available on the pipeline object.  See their docstrings for details.

* `get_defaults`: Gets the default object for this pipeline.  Any properties of this object are inherited by all other
  pipeline objects, so they don't need to be defined on other objects unless you need different values than the 
  defaults.  The default object defines the scheduleType, pipelineLogUri, role and resourceRole.
* `get_schedule`: Gets a schedule object, and sets this schedule as the default schedule for the pipeline.
* `get_shell_command_activity`: Gets a ShellCommandActivity
* `get_ec2_resource`: Get an EC2 resource object.  It will already have its properties such as imageId, keypair, 
   subnetId and security group configured.
* `get_sns_alarm`: Get an SnsAlarm object
* `get_sns_failure_handler`: A version of `get_sns_alarm` which fills in the subject and message properties with a 
  generic mesage which mentions the pipeline name, scheduled execution time, failure status, and the URI of the 
  pipeline web console.  It's meant to be a suitable default onError handler in most cases.

Note that when using the pline.easy module, you still have complete access to all of pline.  The pipeline object passed
to the setup function has `get_xxx` methods for some of the most commonly used pipeline objects, but you are still 
free to create any pline object directly and add it to the pipeline. You might want to do this because you want to use
other pipeline objects for which there is no `get_xxx` method, or because the default behavior of the get_xxx method
isn't what you want.  Here is an example directly creating a SnsError object and adding it to the pipeline:

```python
def setup(pipeline):
    error_handler = pline.actions.SnsAlarm(
        id='MyAlarm',
        name='MyAlarm',
        topicArn=sns_arn,
        role=pipeline.options['PIPELINE_ROLE'],
        subject='Pipeline failed',
        message='The pipeline failed')
        
    pipeline.add(error_handler)
```

### pline.easy config files

The config file that you pass to create_pipeline.py using the --config option is a YAML file that simply defines a 
dictionary of options.  If you run `create_pipeline.py -h`, the help message includes the list of options which 
must be defined in order to create your pipeline.  A sample config file would look like this:

```
EC2_AMI: ami-xx
PIPELINE_RESOURCE_ROLE: DataPipelineDefaultResourceRole
PIPELINE_ROLE: DataPipelineDefaultRole
EC2_SECURITY_GROUP: sg-xyzabc
EC2_SUBNET: subnet-abc123
EC2_KEYPAIR: production20150101
LOG_URI_TEMPLATE: "s3://ferengi/pipelines/{region}/{pipeline_name}"
```

You can pass multiple config files by specifying --config multiple times.  The intention is that you would share one 
config file among multiple pipeline definitions in order to standardize certain defaults.  Pipeline-specific config
options could be specified in a pipeline-specific config file, or passed in via the -o option to create_pipeline.py or
by setting environment variables.

#### Data Pipeline Objects

Every object in a pipeline is an acestor of the `DataPipelineObject` class. Each object 
owns three key attributes:

* `name`
* `id`
* `fields`

The `name` and `id` attributes must be set at initialization time, but `fields` is 
handled internally by the object and should not be accessed directly.

Setting an object's attribute can be done via the initialization call or after the fact:

```python
node = pline.data_nodes.S3DataNode(
    id='MyDataNode1', name='MyDataNode1', workerGroup='TestGroup')
# => <S3DataNode name: "MyDataNode1", id: "MyDataNode1">
node.directoryPath = 's3://bucket/pipeline/'
print node.workerGroup
# => 'TestGroup'
print node.directoryPath
# => 's3://bucket/pipeline/'
```

`Pipeline` instances handle the conversion of pipeline objects to a payload, but objects can
be viewed in `boto`-friendly format by converting them to a `dict`:

```python
dict(node)
{ 'name'   : 'MyDataNode1',
  'id'     : 'MyDataNode1',
  'fields' : [
    { 'key' : 'type',          'stringValue' : 'S3DataNode' },
    { 'key' : 'directoryPath', 'stringValue' : 's3://bucket/pipeline/' },
    { 'key' : 'workerGroup',   'stringValue' : 'TestGroup' }, ] }
```

#### Data Pipeline Parameters

As of `0.2.0`, `pline` supports passing parameters to data pipelines. Parameters can be added to the 
pipeline and passed into `DataPipelineObject` instances.

```python
my_param = pline.parameters.String(
    id = 'MyParam1',
    value = 'Here is the value I am using',
    description = 'This value is extremely important',
    watermark = 'Choose a value between 0 and 99.')
```

#### Typed Data Pipeline Objects/Parameters

Most objects in a data pipeline are typed -- that is, they are given a `type` attribute on initialization
that is added to the `fields` attribute. By default, the type is taken from the name of the class (which
corresponds to the type given by AWS' specs).

Custom classes can override this behavior by defining a `TYPE_NAME` class-level attribute:

```python
class MyCustomS3DataNode(pline.S3DataNode):
    TYPE_NAME = 'S3DataNode'
    # ...

class MyCustomParam(pline.AwsS3ObjectKey):
    TYPE_NAME = 'AwsS3ObjectKey'
    # ...
```


## Example Pipeline

#### Create a pipeline object

```python
pipeline = pline.Pipeline(
    name      = 'MyPipeline',
    unique_id = 'MyPipeline1',
    desc      = 'An example pipeline description',
    region    = 'us-west-2' )
```

#### Connect (optional)

The pipeline will connect to AWS automatically if you have your AWS credentials set at
the environmental level. If you want to connect using a specific configuration:

```python
pipeline.connect(
    aws_access_key_id     = 'my_access_key',
    aws_secret_access_key = 'my_secret_key' )
```

#### Create a schedule object

```python
schedule = pline.Schedule(
    id          = 'Schedule1',
    name        = 'Schedule',
    period      = '1 day',
    startAt     = pline.keywords.startAt.FIRST_ACTIVATION_DATE_TIME,
    occurrences = 1 )
```

#### Create the default pipeline definition 

The pipeline object has a helper-method to create this object with sensible defaults:

```python
definition = pipeline.definition( schedule,
    pipelineLogUri = "s3://bucket/pipeline/log" )
```

#### Create an EC2 resource

This will be the machine running the tasks.

```python
resource = pline.resources.Ec2Resource(
    id           = 'Resource1',
    name         = 'Resource',
    role         = 'DataPipelineDefaultRole',
    resourceRole = 'DataPipelineDefaultResourceRole',
    schedule     = schedule )
```

#### Create an activity

```python
activity = pline.activities.ShellCommandActivity(
    id       = 'MyActivity1',
    name     = 'MyActivity',
    runsOn   = resource,
    schedule = schedule,
    command  = 'echo hello world' )
```


#### Create a parameterized activity and its parameter

```python
param = pline.parameters.String(
    id          = 'myShellCmd',
    value       = 'grep -rc "GET" ${INPUT1_STAGING_DIR}/* > ${OUTPUT1_STAGING_DIR}/output.txt',
    description = 'Shell command to run' )

param_activity = pline.activities.ShellCommandActivity(
    id       = 'MyParamActivity1',
    name     = 'MyParamActivity1',
    runsOn   = resource,
    schedule = schedule,
    command  = param )
```

#### Add the objects to the pipeline

```python
pipeline.add(schedule, definition, resource, activity, param_activity)
```

#### Add the parameters to the pipeline

```python
pipeline.add_param(param)
```

#### View the pipeline definition payload

```python
print pipeline.payload()
```

#### Validate the pipeline definiton

```python
pipeline.validate()
```

#### Create the pipeline in AWS

This will send the request to create a pipeline through boto

```python
pipeline.create()
```

#### Adding new objects to the pipeline

Sometimes you may want to add an object to the pipeline after it has been created

```python
# Add an alert
sns_alarm = pline.actions.SnsAlarm(
    name     = 'SnsAlarm',
    id       = 'SnsAlarm1',
    topicArn = 'arn:aws:sns:us-east-1:12345678abcd:my-arn',
    role     = 'DataPipelineDefaultRole' )

# Associate it with the activity
activity.onFailure = sns_alarm

# Add it to the pipeline
pipeline.add(sns_alarm)
```

Update the pipeline on AWS and activate it

```python
pipeline.update()
pipeline.activate()
```

## ShellCommand helper

The `ShellCommand` class can be used to compose chained commands

```python
cmd = pline.utils.ShellCommand(
    'docker start registry',
    'sleep 3',
    'docker pull localhost:5000/my_docker',
    'docker stop registry' )
# => docker start registry;\
#    sleep 3;\
#    docker pull localhost:5000/my_docker;\
#    docker stop registry

cmd.append('echo all done')
# => docker start registry;\
#    sleep 3;\
#    docker pull localhost:5000/my_docker;\
#    docker stop registry;\
#    echo all done

activity.command = cmd
```
