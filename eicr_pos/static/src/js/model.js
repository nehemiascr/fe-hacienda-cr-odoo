odoo.define('eicr_pos.models', function (require) {
    "use strict";

    var ajax = require('web.ajax');
    var core = require('web.core');
    var models = require('point_of_sale.models');
    var exports = {};

    var _sequence_next = function(seq){
        var idict = {
            'year': moment().format('YYYY'),
            'month': moment().format('MM'),
            'day': moment().format('DD'),
            'y': moment().format('YY'),
            'h12': moment().format('hh')
        };
        var format = function(s, dict){
            s = s || '';
            $.each(dict, function(k, v){
                s = s.replace('%(' + k + ')s', v);
            });
            return s;
        };
        function pad(n, width, z) {
            z = z || '0';
            n = n + '';
            if (n.length < width) {
                n = new Array(width - n.length + 1).join(z) + n;
            }
            return n;
        }
        var num = seq.number_next_actual;
        var prefix = format(seq.prefix, idict);
        var suffix = format(seq.suffix, idict);
        seq.number_next_actual += seq.number_increment;
        debugger;
        return prefix + pad(num, seq.padding) + suffix;
    };

    var PosModelParent = models.PosModel.prototype;
    models.PosModel = models.PosModel.extend({
        load_server_data: function(){
            var self = this;
            // Load POS sequence object
            console.log('uno self');
            console.log(self);
            self.models.push({
                model: 'ir.sequence',
                fields: [],
                ids:    function(self){
                    console.log('dos self');
                    console.log(self);
                    return [self.config.sequence_id[0]]; },
                loaded: function(self, sequence_id){


                    console.log(sequence_id);

                    },
            });
            //debugger;
            return PosModelParent.load_server_data.apply(this, arguments);
        },
        push_order: function(order, opts) {
            //debugger;
            console.log('push_order');
            console.log(order);
            console.log(opts);
            if (order !== undefined) {
                // revisar si es normal o devolucion . Pendiente !!!
                if (order.get('client') && order.get('client').vat) {
                    order.set({'eicr_consecutivo': this.config.sequence_id.number_next_actual});
                    order.set({'eicr_clave': _sequence_next( this.config.sequence_id)});
                }
                else{
                    order.set({'eicr_consecutivo':  this.config.sequence_id.number_next_actual});
                    order.set({'eicr_clave': _sequence_next(this.config.sequence_id)});
                }
            };
            //debugger;
            //return PosModelParent.push_order.call(order,opts);
            return PosModelParent.push_order.apply(this, arguments);
        }
    });

    var OrderParent = models.Order.prototype;
    models.Order = models.Order.extend({
        export_for_printing: function(attributes){
            var order = OrderParent.export_for_printing.apply(this, arguments);
            order['eicr_clave'] = this.get('eicr_clave');
            order['eicr_consecutivo'] = this.get('eicr_consecutivo');
            order['tipo_documento'] = this.get('tipo_documento');
            //debugger;
            return order;
        },
        export_as_JSON: function() {
            var order = OrderParent.export_as_JSON.apply(this, arguments);
            order['eicr_clave'] = this.get('eicr_clave');
            order['eicr_consecutivo'] = this.get('eicr_consecutivo');
            order['tipo_documento'] = this.get('tipo_documento');
            //debugger;
            return order;
        }
    });

    //models.load_fields('res.company', ['street', 'city', 'state_id', 'zip']);

    return exports;
});