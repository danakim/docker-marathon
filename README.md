Deploy and update Marathon applications based on Docker containers
==========================================================================

Initial deploy
--------------

#### Generate JSON config file for your new application

    deploy.py --generate awesome-app.example.com

#### Edit your application's config to match its needs
The new config file lives in a folder matching its name in the 'deploy/apps' dir in the docker.git repo

    vi apps/awesome-app.example.com/awesome-app.example.com.json

#### Deploy your app to the Marathon cluster

    deploy.py <marathon_cluster_hostname>

#### Commit and push your applications config to the    docker.git repo

    git commit apps/awesome-app.example.com/awesome-app.example.com.json
    git push

** Please respect the following rules when deploying a new application **
* the name (ID) of your app should be a FQDN under which that app should be running (eg: 'awesome-app.example.com). This is used to configure your application in the load balancer. If it is a HTTP based application it will be used to configure the 'virtual host' in the load balancer that will distribute the requests to your container
* the network type needs to be 'BRIDGED', otherwise your containers won't be available
* after you create a new application or modify an existing one, please commit your changes to this git repo so we have a log of changes and a backup of the cluster config - the applications' configs are not saved anywhere else besides this git repo, so be careful!

Update application
------------------
If you want your application to use a new version of your container or change your application's config (CPU, Mem, no. of instances etc), the procedure is very similar to the deploy one

#### Modify your apps JSON config in the docker.git repo

    vi apps/awesome-app.example.com/awesome-app.example.com.json

#### Use the same deploy command.
This is will overwrite the config in Marathon and trigger a new deployment of your application based on the 'upgradeStrategy' defined in your config

    deploy.py awesome-app.example.com

Restart application
-------------------
If for any reason you would like to do a rolling restart of your application, using the currently running config, use the following command. It will trigger a new deployment of your application also based on the configured 'upgradeStrategy'.

    deploy.py --restart awesome-app.example.com

Generate the Nginx configs
--------------------------
This repository contains another tool, that can be used to generate a Nginx config for each application running in Marathon. It will be used to load balance the traffic to all the Docker instances (Host IP + Container port) running under the application.

The script is meant to be run in a loop, either as a cron job or a Supervisor program (recommended). You can find the 'generate_nginxconfig_marathon.py' under the 'proxy' directory. It assumes it runs on the same host(s) that run Nginx, the load balancing hosts / instances / servers.
