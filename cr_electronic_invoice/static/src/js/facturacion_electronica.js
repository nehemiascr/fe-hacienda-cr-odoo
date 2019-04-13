
odoo.define('facturacion_electronica.prueba', function (require) {
    "use strict";

    require('web.dom_ready');
    var WebClient = require('web.WebClient');
    var web_client = require('web.web_client');


    // var core = require('web.core');
    // var web_client = require('web.web_client');



    // var _t = core._t;
    // var qweb = core.qweb;

    var mensaje = 'hola mundo';
    console.log(mensaje);

    console.log(WebClient);
    console.log(web_client);

    // web_client.set_title(mensaje);
    // web_client.do_notify('hola');
    // console.log(web_client.do_warn('mundo'));
    //
    // this.do_warn('okok');
    // self.do_warn('okok');



    // console.log(Notification);

    // var n = new Notification.Notification('Hola','Mundo', true);
    // console.log(n);

    var Widget = require('web.Widget');

    var Notification = require('web.notification');
    var nm = new Notification.NotificationManager;
    console.log('nm');
    console.log(nm);



    nm.notify('hola', 'mundo', true);



    // nm.notify(
    //         _t(':)'),
    //         _t('hola mundo'),
    //         true
    //     );


    return {
        Mensaje:mensaje,
    }
});