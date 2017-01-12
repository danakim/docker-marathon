#!/usr/bin/python3.4
'''
A deployment tool for Docker containers to a Marathon cluster.
Check out the help for more details.

Author: Dan Achim <dan@hostatic.ro>
'''

import click
import os
import sys
import json
import requests
import re
import configparser
from jinja2 import Template

### Read config ###
config = configparser.ConfigParser()
config.read('/etc/docker-deploy.cfg')

marathon_user = config['marathon']['user']
marathon_pass = config['marathon']['pass']
live_cluster = config['marathon']['live_cluster']
backup_clusters = config['marathon']['backup_clusters'].split(',')
###

### Global variables ###
# Script path
script_path = os.path.dirname(__file__)
###

### Functions ###
# Validate if the given app name is a valid hostname
def is_valid_hostname(hostname):
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1]
    allowed = re.compile("(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))

# Remove all proxy vars from the environment as not to interfere
# with any HTTP API calls
def remove_proxy():
    for key in list(os.environ):
        if key.lower().endswith('proxy'): del os.environ[key]

# Friendly reminder to commit your changes to the git repo
def git_commit_reminder(name,action):
    click.secho('Do not forget to commit your changes to the conf file to git!'
                '\nThese configs do not exist anywhere else but in this repo!'
                '\n\ngit %s apps/%s/%s.json\n' % (name,name,action),fg='magenta')

# Generates a basic JSON config file for our Marathon app from a template
def generate_app_template(name, cluster, external='off'):
    directory = "%s/apps/%s" % (script_path,name)
    # Make the config directory
    if not os.path.exists(directory):
        try:
            os.mkdir(directory)
        except Exception as e:
            click.secho('Can not create app dir: ' + str(e), fg='red')
            sys.exit(3)
    # Generate the template
    try:
        template_file = open(script_path + '/templates/marathon.json')
        template = Template(template_file.read())
        result = template.render(app_name=name, cluster=cluster, nfs=nfs,
                                 external=external)
        with open("%s/%s.json" % (directory,name), "w") as app_template:
            app_template.write(result)
    except Exception as e:
        click.secho('Can not write template: ' + str(e), fg='red')
        sys.exit(3)
    click.secho("Template file %s/%s.json has been successfully generated!" %
                (directory,name), fg='green')

# Restart the application
def restart_app(name, cluster):
    url = "https://%s:%s@%s/v2/apps" % (marathon_user, marathon_pass, cluster)
    headers = {'Content-type': 'application/json'}

    # Trigger a restart
    try:
        r = requests.post('%s/%s/restart' % (url,name), timeout=10)
    except Exception as e:
        click.secho("Can not trigger the restart of %s: %s" % (name,str(e)),
                    fg='red')
        sys.exit(3)
    if r.status_code == 200:
        click.secho('Succesfully restarted app %s!\n%s\nYou can follow it here:'
                    ' https://%s/ui/#/deployments'
                    % (name, r.text, cluster), fg='green')
    else:
        click.secho('%s\'s API received our command but didn\'t like it:\n'
                    '%s. Status code: %s' % (cluster, r.text, r.status_code),
                    fg='yellow')

# Query Marathon's API for the current config for our application
def query_app(name, cluster):
    url = "https://%s:%s@%s/v2/apps" % (marathon_user, marathon_pass, cluster)
    headers = {'Content-type': 'application/json'}

    # GET the config
    try:
        r = requests.get('%s/%s' % (url,name), timeout=10)
        ver = requests.get('%s/%s/versions' % (url,name), timeout=10)
    except Exception as e:
        click.secho("Can not get the config from %s/%s: %s" % (url,name,str(e)),
                    fg='red')
        sys.exit(3)
    # Print some nice output
    output = json.loads(r.text)
    versions = json.loads(ver.text)
    hosts = []
    click.secho(output['app']['id'].replace('/',''), fg='blue')
    click.secho('---------------------------------', fg='blue')
    for entry in ['cpus','mem','disk','instances','env','cmd','args','user',
                  'healthChecks','upgradeStrategy','labels','deployments',
                  'version']:
        click.secho('\t' + str(entry) + ': ' + str(output['app'][entry]),
                    fg='yellow')
    click.secho('\told_versions: ' + str(versions['versions']), fg='yellow')
    for entry in ['type','volumes']:
        click.secho('\t' + str(entry) + ': ' +
                    str(output['app']['container'][entry]),
                    fg='yellow')
    for entry in ['image','network','portMappings','privileged','parameters',
                  'forcePullImage']:
        click.secho('\t' + str(entry) + ': ' +
                    str(output['app']['container']['docker'][entry]),
                    fg='yellow')
    for task in output['app']['tasks']:
        hosts.append(str(task['host']))
    click.secho('\thosts: ' + str(hosts), fg='yellow')

# Send our config JSON file to Marathon's API to create a new
# application or update an existing one
def deploy_app(name, cluster, force=False):
    url = "https://%s:%s@%s/v2/apps" % (marathon_user, marathon_pass, cluster)
    headers = {'Content-type': 'application/json'}
    directory = "%s/apps/%s" % (script_path,name)

    # Read our app config
    try:
        with open('%s/%s.json' % (directory,name)) as config_file:
            config = json.load(config_file)
    except Exception as e:
        click.secho("Can not read config file %s/%s.json: %s." %
                    (directory,name,str(e)), fg='red')
        sys.exit(3)

    # POST our app config to Marathon
    click.secho("Deploying the application to the %s cluster.\n" % cluster,
                fg='blue')
    try:
        params = '?force=true' if force else ''
        uri = '%s/%s%s' % (url, name, params)
        r = requests.put(uri, data=json.dumps(config),
                        headers=headers, timeout=10)
    except Exception as e:
        click.secho("Can not send config to %s: %s" % (url,str(e)), fg='red')
        sys.exit(3)
    if r.status_code in [200,201] :
        click.secho('Succesfully deployed app %s to %s!\n%s\n\nYou can follow '
                    'it here: https://%s/ui/#/deployments\n'
                    % (name,cluster,r.text,cluster), fg='green')
    else:
        click.secho('%s\'s API received the config but didn\'t like it:\n'
                    '%s. Status code: %s' % (cluster, r.text, r.status_code),
                    fg='yellow')

# Delete an application from Marathon
def delete_app(name, cluster):
    url = "https://%s:%s@%s/v2/apps" % (marathon_user, marathon_pass, cluster)
    headers = {'Content-type': 'application/json'}

    click.secho("Deleting the application from the %s cluster.\n" % cluster,
                fg='blue')
    try:
        r = requests.delete('%s/%s' % (url,name), headers=headers, timeout=10)
    except Exception as e:
        click.secho("Can not delete app from %s: %s" % (url,str(e)), fg='red')
        sys.exit(3)
    if r.status_code in [200,201] :
        click.secho('Succesfully deleted app %s from %s!\n%s\n\nYou can follow'
                    % (name,cluster,r.text), fg='green')
    elif r.status_code == 404:
        click.secho('No such app in the %s cluster: %s\n' % (name,cluster),
                    fg='yellow')
    else:
        click.secho('%s\'s API received the delete command but didn\'t like '
                    'it:\n %s.Status code: %s' % (cluster,r.text,r.status_code),
                    fg='yellow')
###

# Define our CLI commands, args, options and actions #
@click.command()
@click.option('--cluster',
              help='Marathon cluster hostname to run this app on.')
@click.option('--generate', is_flag=True,
              help='Generate a basic config file for your application.')
@click.option('--external', default='off',
              help='Set this flag to "on" when generating the initial config '
                   'if you wish to make this application available to the '
                   'outside world as well. Default: off.')
@click.option('--query', is_flag=True,
              help='Show the currently running config in Marathon\
                    for your application.')
@click.option('--restart', is_flag=True,
              help='Trigger a rolling restart of the application.')
@click.option('--delete', is_flag=True,
              help='Delete an application from the Marathon cluster.')
@click.option('--force', is_flag=True,
              help='Force deployment. (Pass ?force=true to marathon\
                    API call.')
@click.argument('name')

def deploy(cluster, generate, external, query, restart, delete, force, name):
    '''
    Deployment tool for Docker containers.
    This tool helps you deploy your Docker containers to a Marathon cluster
    running on top of Mesos. It reads the config from a local JSON file that
    lives in the 'apps' directory, under a dir with the same name as the app.\n
    Ex: apps/awesome-app.example.com/awesome-app.example.com.json

    The tool can help you generate that config file from a template, using
    the '--generate' flag.\n
    Ex: deploy.py --generate awesome-app.example.com

    The name of the application needs to be a valid FQDN.
    '''
    if is_valid_hostname(name) == False:
        click.secho('%s is not a valid hostname.' % name, fg='red')
        sys.exit(3)
    if generate:
        generate_app_template(name, cluster, external=external)
    elif query:
        remove_proxy()
        query_app(name, cluster)
    elif restart:
        remove_proxy()
        restart_app(name, cluster)
    elif delete:
        remove_proxy()
        delete_app(name, cluster)
        git_commit_reminder(name,'rm')
    else:
        remove_proxy()
        deploy_app(name, cluster, force)
        git_commit_reminder(name,'commit')

# Call the main function
if __name__ == '__main__':
    deploy()
