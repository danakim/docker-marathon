#!/usr/bin/python3.4
'''
A supervisor script that queries the Marathon API and generates Nginx configs
based on the data returned.

Author: Dan Achim <dan@hostatic.ro>
'''

import os
import sys
import json
import requests
import socket
import time
import filecmp
import subprocess
from jinja2 import Template

### Global variables ###
script_path = os.path.dirname(__file__)
hostname = socket.getfqdn()
dc = hostname.split('.')[1]
marathon_api_host = 'localhost:8080'
marathon_api_path = '/v2'
sleep_between_checks = 3
tmp_directory = '/tmp'
live_directory = '/etc/nginx/sites-enabled'
###


class AppData(dict):

    """ Tiny dict wrapper with helper method to get labels """

    def get_label(self, label, default):
        return self['app']['labels'].get(label, default)

### Functions ###
def cur_time():
    return time.strftime("%Y/%m/%d %H:%M:%S")

# Remove all proxy vars from the environment as not to interfere
# with any HTTP API calls
def remove_proxy():
    for key in list(os.environ):
        if key.lower().endswith('proxy'): del os.environ[key]

# Generic function to request a config JSON from Marathon
def get_http_json(url_host, url_path, url_params):
    url = 'http://' + url_host + url_path
    try:
        resp = requests.get(url=url, params=url_params, timeout=5)
        data = json.loads(resp.text)
    except Exception as e:
        print('%s Can not get data from Marathon\'s API: %s' %
              (cur_time(), str(e)))
        sys.exit(3)
    return AppData(data)

# Reload Nginx
def reload_nginx():
    command = ["service", "nginx", "reload"]
    try:
        output = subprocess.check_output(command)
    except Exception as e:
        print("%s Error reloading Nginx: %s" % (cur_time(), str(e)))
        return
    return output

# Check Nginx config
def check_nginx_conf(default_tmp_file):
    command = ["/sbin/nginx", "-t", "-c", default_tmp_file]
    try:
        child = subprocess.Popen(command)
        streamdata = child.communicate()[0]
        return_code = child.returncode
    except Exception as e:
        print("%s Error checking Nginx config: %s" % (cur_time(), str(e)))
        return 2
    return return_code

# Generate a valid Nginx config based on the data from Marathon
def generate_nginx_config(app):
    app_json = get_http_json(marathon_api_host,
                             marathon_api_path+'/apps/' + app, {})

    nginx_server_name = app_json.get_label('nginx_server_names', None)
    if nginx_server_name is not None:
        split_name = nginx_server_name.split('.')
        if len(split_name) == 3: env = 'default'
        else: env = split_name[1]
    else:
        print('We need the "nginx_server_names" label defined!\nCheck your '
              'app\'s JSON config.\nNot generating a Nginx conf for %s\n' % app)
        return

    ssl = app_json.get_label('ssl', 'on')
    ssl_redirect = app_json.get_label('ssl_redirect', 'on')
    auth = app_json.get_label('auth', 'off')
    auth_group = app_json.get_label('auth_group', 'nginx')
    protocol = app_json.get_label('protocol', 'http')
    custom_conf_inc = app_json.get_label('custom_conf_inc', 'none')
    externally_avaialable = app_json.get_label('external', 'off') == 'on'

    backends = []
    if 'tasks' in app_json['app']:
        for task in app_json['app']['tasks']:
            backend = task['host'] + ":" + str(task['ports'][0])
            backends.append(backend)

    http_port = 81 if externally_avaialable else 80
    https_port = 8443 if externally_avaialable else 443

    template = pick_template(ssl, ssl_redirect)

    tmp_file, default_tmp_file = create_temp_file(app, template, \
                                                  nginx_server_name, \
                                                  auth, auth_group, env,
                                                  custom_conf_inc, backends, \
                                                  protocol, http_port, \
                                                  https_port)

    compare_temp_file(app, tmp_file, default_tmp_file)

def pick_template(ssl, ssl_redirect):
    # Choose which template to use based on the settings read above
    template = 'nginx_conf_ssl.conf' #  by default ssl and ssl_redirect are on
    if ssl != 'on':
        template = 'nginx_conf_nossl.conf'
    elif ssl_redirect != 'on':
        template = 'nginx_conf_ssl_noredirect.conf'

    return template

def create_temp_file(app, template, nginx_server_name, auth, auth_group, env \
                     custom_conf_inc, backends, protocol, http_port,https_port):

    # Write the resulting template to a temporary file
    tmp_file = "%s/marathonapp-%s.conf" % (tmp_directory, app)
    default_tmp_file = "%s/nginx_default.conf" % tmp_directory
    try:
        template_file = open(script_path + '/templates/%s' % template)
        default_template_file = open(script_path + '/templates/nginx_default.conf')
        template = Template(template_file.read())
        default_template = Template(default_template_file.read())
        result = template.render(nginx_server_name=nginx_server_name,
                                 auth=auth, auth_group=auth_group, env=env,
                                 custom_conf_inc=custom_conf_inc,
                                 backends=backends, protocol=protocol,
                                 http_port=http_port, https_port=https_port)
        default_result = default_template.render(tmp_directory=tmp_directory,
                                                 app=app)
        with open(tmp_file, "w") as tmp_app_template:
            tmp_app_template.write(result)
        with open(default_tmp_file, "w") as default_nginx_template:
            default_nginx_template.write(default_result)

    except Exception as e:
        print("%s Can not write temporary template for %s: %s" %
              (cur_time(), app, str(e)))
        return

    return tmp_file, default_tmp_file

def compare_temp_file(app, tmp_file, default_tmp_file):
    # Compare the temporary template with the currently live one
    # if there is one, if not just put the file directly live
    live_file = "%s/marathonapp-%s.conf" % (live_directory, app)
    if os.path.isfile(live_file) == False:
        file_comp = False
    else:
        try:
            file_comp = filecmp.cmp(tmp_file, live_file)
        except Exception as e:
            print("%s Something went wrong comparing the conf files "
                    "for %s: %s" % (cur_time(), app, str(e)))
            return

    if file_comp == False:
        move_config_file(app, default_tmp_file, tmp_file, live_file)
        reload_nginx()

    remove_tempfile(app, tmp_file, default_tmp_file)

def move_config_file(app, default_tmp_file, tmp_file, live_file):
    print("%s Changes detected for %s, reloading Nginx to activate new "
          "config." % (cur_time(),app))
    rc = check_nginx_conf(default_tmp_file)
    if rc != 0:
        print("%s Nginx config check failed! Not activating it." % cur_time())
        return
    try:
        os.rename(tmp_file, live_file)
    except Exception as e:
        print("%s Error! Could not move new config file: %s" %
              (cur_time(), str(e)))
        return

    os.remove(default_tmp_file)

def remove_tempfile(app, tmp_file, default_tmp_file):
    print("%s No changes detected for %s" % (cur_time(), app))
    try:
        os.remove(tmp_file)
        os.remove(default_tmp_file)
    except Exception as e:
        print("%s Error: %s" % (cur_time(), app))
        return

# Cleanup old Nginx conf files for apps that are not in Marathon any more
def cleanup_old_nginx_configs(apps):
    for conf in os.listdir(live_directory):
        if str(conf).startswith('marathonapp-'):
            conf = conf.replace('marathonapp-','').strip('.conf')
            if conf not in apps:
                try:
                    print("%s Deleting %s/marathonapp-%s.conf" %
                          (cur_time(), live_directory, conf))
                    os.remove('%s/marathonapp-%s.conf' % (live_directory,conf))
                except Exception as e:
                    print("%s Error: %s" % (cur_time(), e))
                    return

# Get rid of the nasty ENV proxies
remove_proxy()

# Get a list of apps from the Marathon API
marathon_apps_json = get_http_json(marathon_api_host,
                                   marathon_api_path+'/apps', {})
marathon_apps = []
for app in marathon_apps_json['apps']:
    app_id = app['id'].replace('/','')
    marathon_apps.append(app_id)

# Main loop
def main_loop():
    cleanup_old_nginx_configs(marathon_apps)
    for app in marathon_apps:
        generate_nginx_config(app)
    time.sleep(sleep_between_checks)

if __name__ == '__main__':
    main_loop()
